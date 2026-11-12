"""Keyword extraction of visits, procedure-to-visit tags, staffing and review flags.

The schedule PDFs are synthetic: ruled tables drawn by the make_table_pdf
fixture, the way protocols lay out a Schedule of Activities.
"""

import re
import textwrap

import pytest

import soa
from extract import EQUIPMENT, PHARMACY, PROCEDURES, TECHNOLOGY, _flat, _is_toc, keyword_items, parse_pdf, plan_from_parsed, safety_items
from extractor import KeywordExtractor
from models import OperationalPlan

TITLE = "Schedule of Activities"
HEADER = [
    ["Procedure", "Screening^a", "Treatment", None, "End of Study", "Notes"],
    ["", "Day -28 to -1", "Day 1", "Week 4 ±3 days", "", ""],
]
BODY = [
    ["Clinical Assessments", None, None, None, None, None],
    ["Informed consent", "X", "", "", "", ""],
    ["Vital signs", "X", "x", "•", "X", "seated"],
    ["Hematology", "X", "", "(X)", "X", ""],
    ["Demographics^c", "X", "", "", "", ""],
]


def _plan(pdf: bytes) -> OperationalPlan:
    return KeywordExtractor().extract(parse_pdf(pdf, "test.pdf"))


def _proc(plan, name):
    return next(p for p in plan.procedures if p.name == name)


def _flag(plan, section):
    return getattr(plan.section_reviews, section)


# ---------- a clean table ----------

def test_clean_table_gives_visits_with_page_and_confidence(make_table_pdf):
    plan = _plan(make_table_pdf([(TITLE, HEADER + BODY)]))

    assert [(v.id, v.name, v.day, v.window) for v in plan.visits] == [
        ("V1", "Screening Day -28 to -1", "Day -28 to -1", None),  # footnote letter dropped
        ("V2", "Day 1", "Day 1", None),
        ("V3", "Week 4 ±3 days", "Week 4", "±3 days"),
        ("V4", "End of Study", None, None),
    ]
    assert all(v.source_page == 1 and v.confidence == 0.8 for v in plan.visits)
    assert 'Under "Treatment"' in plan.visits[1].notes
    assert not _flag(plan, "visits").needs_review


def test_clean_table_tags_procedures_with_visits(make_table_pdf):
    plan = _plan(make_table_pdf([(TITLE, HEADER + BODY)]))

    # Rows that match a keyword procedure tag it; its name and page stay as found by keyword.
    assert _proc(plan, "Informed consent").visits == ["V1"]
    assert _proc(plan, "Vital signs").visits == ["V1", "V2", "V3", "V4"]  # X, x and • all count
    hematology = _proc(plan, "Hematology")
    assert hematology.visits == ["V1", "V3", "V4"]
    assert "conditional or optional at Week 4 ±3 days" in hematology.notes
    # A row no keyword knows becomes its own procedure, under its table section.
    demo = _proc(plan, "Demographics")
    assert (demo.category, demo.visits, demo.source_page, demo.confidence) == ("Clinical Assessments", ["V1"], 1, 0.75)
    assert not _flag(plan, "procedures").needs_review


def test_procedures_found_only_by_keyword_keep_no_visits(make_table_pdf):
    pages = [(TITLE, HEADER + BODY), ("A 12-lead ECG is recorded if clinically indicated.", None)]
    plan = _plan(make_table_pdf(pages))
    assert _proc(plan, "12-lead ECG").visits == []


def test_keyword_sections_are_unchanged_by_the_schedule(make_table_pdf):
    pdf = make_table_pdf([
        (f"{TITLE} for the study drug", HEADER + BODY),
        ("Serious adverse events are reported within 24 hours. Samples go in a centrifuge.\n"
         "Data are entered in the EDC. The study drug is stored at 2-8 °C.\n"
         "Investigational product accountability is kept.", None),
        ("The study drug is given daily.", None),
    ])
    parsed = parse_pdf(pdf, "test.pdf")
    plan = plan_from_parsed(parsed)
    flat = [_flat(t) for t in parsed.pages]
    skip = {i for i, t in enumerate(parsed.pages) if _is_toc(t)}

    assert plan["safety"] == safety_items(flat, skip)
    assert plan["equipment"] == keyword_items(EQUIPMENT, flat, skip, lambda r: {"item": r[0], "purpose": r[1]})
    assert plan["technology"] == keyword_items(TECHNOLOGY, flat, skip, lambda r: {"system": r[0], "purpose": r[1]})
    assert plan["pharmacy"]["items"] == keyword_items(PHARMACY, flat, skip, lambda r: {"item": r[0]})
    # Every keyword procedure is still there, first and in order, with the
    # same name, category, page and confidence; only visits and notes grow.
    keyword = keyword_items(PROCEDURES, flat, skip, lambda r: {"name": r[0], "category": r[1], "visits": []})
    for before, after in zip(keyword, plan["procedures"]):
        same = ("name", "category", "source_page", "confidence")
        assert {k: after[k] for k in same} == {k: before[k] for k in same}
        assert after["notes"].startswith(before["notes"])
    OperationalPlan.model_validate(plan)


def test_grouped_columns_and_a_shared_window(make_table_pdf):
    # The layout of NCT03872401: numbered years under a group heading, and a
    # window sentence across them.
    header = [
        ["Procedure", "Screening", "Treatment Period (years)", None, "EOS"],
        ["", "", "1 (week 48)", "2 (week 96)", ""],
        ["", "", "Visits have a ±7 day window", None, ""],
    ]
    body = [["Informed consent", "X", "", "", ""], ["Vital signs", "X", "X", "X", "X"]]
    plan = _plan(make_table_pdf([(TITLE, header + body)]))

    assert [(v.name, v.day, v.window) for v in plan.visits] == [
        ("Screening", None, None),
        ("Treatment Period (years) 1 (week 48)", "Week 48", "±7 days"),
        ("Treatment Period (years) 2 (week 96)", "Week 96", "±7 days"),
        ("EOS", None, None),
    ]


def test_a_heading_that_is_not_a_visit_is_flagged(make_table_pdf):
    header = [["Procedure", "Screening", "Day 1", "Kit B"]]
    body = [["Informed consent", "X", "", ""], ["Vital signs", "X", "X", "X"], ["Physical examination", "X", "X", ""]]
    plan = _plan(make_table_pdf([(f"{TITLE}. Kit B is the study kit shipped to the site.", header + body)]))

    kit = plan.visits[-1]
    assert (kit.name, kit.confidence) == ("Kit B", 0.55)
    assert "doesn't look like a visit" in kit.notes
    assert "1 column heading" in _flag(plan, "visits").reason


# ---------- a table split across pages ----------

def test_table_split_across_pages_with_repeated_header(make_table_pdf):
    page2 = HEADER + [
        ["Laboratory", None, None, None, None, None],
        ["Urinalysis", "X", "", "", "X", ""],
        ["Vital signs", "", "", "", "", ""],
    ]
    plan = _plan(make_table_pdf([(TITLE, HEADER + BODY), (f"{TITLE} (continued)", page2)]))

    assert [v.id for v in plan.visits] == ["V1", "V2", "V3", "V4"]  # not repeated
    urinalysis = _proc(plan, "Urinalysis")
    assert urinalysis.visits == ["V1", "V4"]
    assert "page 2" in urinalysis.notes
    assert _proc(plan, "Vital signs").visits == ["V1", "V2", "V3", "V4"]  # merged across pages


def test_table_continued_without_header_or_title(make_table_pdf):
    page2 = [
        ["Urinalysis", "X", "", "", "X", ""],
        ["Questionnaires", "", "X", "X", "", ""],
    ]
    plan = _plan(make_table_pdf([(TITLE, HEADER + BODY), ("Protocol 123, page 2", page2)]))

    assert len(plan.visits) == 4
    assert _proc(plan, "Urinalysis").visits == ["V1", "V4"]
    assert _proc(plan, "Questionnaires").visits == ["V2", "V3"]


def test_columns_differ_between_pages(make_table_pdf):
    page2 = [
        ["Procedure", "Week 8", "Week 12", "Follow-up", "Notes"],
        ["Vital signs", "X", "X", "", ""],
        ["Urinalysis", "", "X", "X", ""],
    ]
    plan = _plan(make_table_pdf([(TITLE, HEADER + BODY), (TITLE, page2)]))

    assert [v.name for v in plan.visits][4:] == ["Week 8", "Week 12", "Follow-up"]
    assert [v.source_page for v in plan.visits] == [1, 1, 1, 1, 2, 2, 2]
    assert _proc(plan, "Vital signs").visits == ["V1", "V2", "V3", "V4", "V5", "V6"]


# ---------- no schedule ----------

def test_no_schedule_flags_visits_and_procedures(sample_pdf_bytes):
    # The sample has a schedule written as text, not a table.
    plan = _plan(sample_pdf_bytes)

    assert plan.visits == []
    assert plan.procedures and all(p.visits == [] for p in plan.procedures)
    assert _flag(plan, "visits").needs_review
    assert "No Schedule of Activities table" in _flag(plan, "visits").reason
    assert "aren't linked to visits" in _flag(plan, "procedures").reason


def test_a_table_without_marks_is_not_a_schedule(make_table_pdf):
    contacts = [
        ["Role", "Name", "Phone", "Email"],
        ["Medical monitor", "TBD", "555-0100", "mm@example.org"],
        ["Sponsor contact", "TBD", "555-0101", "sc@example.org"],
    ]
    plan = _plan(make_table_pdf([(f"See the {TITLE} in Section 1.3. X X X", contacts)]))
    assert plan.visits == []
    assert _flag(plan, "visits").needs_review


# ---------- unknown marks ----------

def test_unknown_marks_are_not_tagged_and_are_flagged(make_table_pdf):
    body = BODY + [
        ["Concomitant medications", "X", "Q4W", "Q4W", "X", ""],
        ["Adverse events", "", "continually", None, "X", ""],
    ]
    plan = _plan(make_table_pdf([(TITLE, HEADER + body)]))

    conmeds = _proc(plan, "Concomitant medication review")
    assert conmeds.visits == ["V1", "V4"]
    assert 'Unrecognized entry "Q4W" at Day 1, Week 4 ±3 days' in conmeds.notes
    ae = _proc(plan, "Adverse event assessment")
    assert ae.visits == ["V4"]  # the merged "continually" cell tags nothing
    assert '"continually" at Day 1, Week 4 ±3 days' in ae.notes

    flag = _flag(plan, "procedures")
    assert flag.needs_review and '"Q4W"' in flag.reason and "2 schedule entries" in flag.reason


def test_schedule_only_row_with_unknown_marks_has_lower_confidence(make_table_pdf):
    body = BODY + [["Diary review", "", "Q2W", "Q2W", "", ""]]
    plan = _plan(make_table_pdf([(TITLE, HEADER + body)]))
    diary = _proc(plan, "Diary review")
    assert (diary.visits, diary.confidence) == ([], 0.5)
    assert "Q2W" in diary.notes


@pytest.mark.parametrize("text", ["X", "x", "✓", "✔", "√", "•", "●", "X*", "X†", "", ""])
def test_marks_that_tag_a_visit(text):
    assert soa.mark(text) == "x"


@pytest.mark.parametrize("text", ["(X)", "[X]", "( x )"])
def test_bracketed_marks_are_conditional(text):
    assert soa.mark(text) == "conditional"


@pytest.mark.parametrize("text", ["", "Q4W", "continually", "X-ray", "(X) Sample collection x1", "—"])
def test_entries_that_are_not_marks(text):
    assert soa.mark(text) is None


def test_visit_timing_helpers():
    assert soa.day("Day -28 to -1") == "Day -28 to -1"
    assert soa.day("1 (week 48)") == "Week 48"
    assert soa.window("These visits will have a  7 day window") == "±7 days"
    assert soa.window("Week 4 +/- 3 days") == "±3 days"
    assert soa.window("Day 1") is None


# ---------- staffing ----------

STAFF_TEXT = textwrap.fill(
    "The investigator is responsible for the conduct of the study. The investigator will keep a list of "
    "appropriately qualified persons to whom study duties are delegated. The rater must be certified in "
    "the use of the HAM-D scale. A research nurse will draw blood samples. Scans are read by a "
    "board-certified radiologist. The unblinded pharmacist prepares the infusion.",
    90,
)
TITLE_PAGE = "Synthetic protocol title page. A study of drug X in adults, for testing only.\nNo real data."


def test_staffing_roles_with_source_page(make_pdf):
    plan = _plan(make_pdf([TITLE_PAGE, STAFF_TEXT]))
    roles = {s.role: s for s in plan.staffing}

    assert set(roles) == {"Principal Investigator", "Research nurse", "Rater", "Radiologist", "Pharmacist", "Unblinded staff"}
    assert all(s.source_page == 2 for s in plan.staffing)
    assert not _flag(plan, "staffing").needs_review


def test_qualifications_are_quoted_only_when_tied_to_the_role(make_pdf):
    plan = _plan(make_pdf([TITLE_PAGE, STAFF_TEXT]))
    roles = {s.role: s for s in plan.staffing}

    assert roles["Rater"].qualifications == "certified in the use of the HAM-D scale"
    assert roles["Radiologist"].qualifications == "board-certified"
    assert "Qualification quoted from page 2" in roles["Rater"].notes
    # "appropriately qualified persons" describes other people, not the investigator.
    assert roles["Principal Investigator"].qualifications is None
    assert roles["Research nurse"].qualifications is None
    # Never invented: every qualification is text from the PDF.
    flat = re.sub(r"\s+", " ", STAFF_TEXT)  # the text layer, with line breaks collapsed
    assert all(s.qualifications in flat for s in plan.staffing if s.qualifications)


def test_investigators_brochure_is_not_a_role(make_pdf):
    plan = _plan(make_pdf([TITLE_PAGE, "See the Investigator's Brochure and the Investigator Brochure for background\non drug X, its safety and dosing."]))
    assert plan.staffing == []
    assert "No site roles" in _flag(plan, "staffing").reason


# ---------- billing and empty sections ----------

def test_billing_is_empty_and_flagged_for_manual_entry(make_table_pdf):
    plan = _plan(make_table_pdf([(TITLE, HEADER + BODY)]))
    assert plan.billing == []
    assert _flag(plan, "billing").needs_review
    assert "clinical trial agreement" in _flag(plan, "billing").reason


def test_every_empty_section_has_a_reason(make_pdf):
    plan = _plan(make_pdf([TITLE_PAGE + "\nNothing operational is described anywhere in this short file."]))
    for section in ("visits", "procedures", "staffing", "safety", "billing", "equipment", "pharmacy", "technology"):
        flag = _flag(plan, section)
        assert flag.needs_review and flag.reason, section
