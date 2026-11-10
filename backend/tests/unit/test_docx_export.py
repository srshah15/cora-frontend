"""Unit tests for the Word export builder (backend/docx_export.py).

Each test builds a document from the frontend's sample plan, re-opens the
bytes with python-docx, and checks the content a reviewer relies on.
"""

import io
from datetime import date

import pytest
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pydantic import ValidationError

from docx_export import (
    DRAFT_NOTICE,
    NONE_FOUND,
    SECTIONS,
    DocxExportRequest,
    build_plan_docx,
    export_filename,
)
from models import OperationalPlan

# Sample-plan indices (see tests/fixtures/sample_plan.json):
#   procedures:9  Urine pregnancy test (0.62, has notes)
#   procedures:10 PK blood sample      (0.58)
#   safety:2      Unanticipated problem (0.64)
#   billing:2     Spirometry           (0.55, has notes)
#   billing:4     Physical exam        (0.61, no notes)
REVIEWS = {
    "procedures:9": {
        "status": "edited",
        "comment": "SoA table is authoritative",
        "reviewer": "Jane Reviewer",
        "at": "2026-11-09T15:04:05.000Z",
        "original": {"name": "Urine pregnancy test", "category": "Lab", "visits": ["V2", "V3", "V4", "V5"]},
    },
    "procedures:10": {"status": "rejected", "comment": "Duplicate of lab draw", "reviewer": "Jane Reviewer", "at": "2026-11-09T15:05:00Z"},
    "safety:2": {"status": "accepted", "reviewer": "Jane Reviewer", "at": "2026-11-09T15:06:00Z"},
}


def _open(data: bytes):
    return Document(io.BytesIO(data))


def _build(plan_dict, reviews=REVIEWS, **kw):
    kw.setdefault("export_date", date(2026, 11, 9))
    return _open(build_plan_docx(OperationalPlan.model_validate(plan_dict), reviews, **kw))


def _cell_text(cell) -> str:
    return "\n".join(p.text for p in cell.paragraphs)


def _headings(doc):
    return [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]


def _section_blocks(doc, label):
    """Paragraphs and tables between a Heading 1 and the next one."""
    out, inside = [], False
    for block in doc.iter_inner_content():
        is_h1 = isinstance(block, Paragraph) and block.style.name == "Heading 1"
        if is_h1:
            if inside:
                break
            inside = block.text == label
            continue
        if inside:
            out.append(block)
    return out


def _section_table(doc, label) -> Table:
    tables = [b for b in _section_blocks(doc, label) if isinstance(b, Table)]
    assert len(tables) == 1, f"expected one table under {label!r}"
    return tables[0]


def _row(table: Table, first_cell: str) -> dict:
    """A table row as {header: cell text}, found by its first-column text."""
    headers = [c.text for c in table.rows[0].cells]
    for r in table.rows[1:]:
        if r.cells[0].text == first_cell:
            return {h: _cell_text(c) for h, c in zip(headers, r.cells)}
    raise AssertionError(f"no row {first_cell!r}")


# --- Structure --------------------------------------------------------------

def test_returns_docx_bytes(sample_plan):
    data = build_plan_docx(OperationalPlan.model_validate(sample_plan), REVIEWS)
    assert data[:2] == b"PK"  # .docx is a zip container
    _open(data)


def test_every_category_heading_appears_in_order(sample_plan):
    headings = _headings(_build(sample_plan))
    labels = [label for _, label in SECTIONS]
    assert [h for h in headings if h in labels] == labels


def test_header_has_metadata_date_and_draft_notice(sample_plan):
    doc = _build(sample_plan)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert doc.paragraphs[0].style.name == "Title"
    assert "XR-214 Asthma Phase II" in doc.paragraphs[0].text
    assert DRAFT_NOTICE in text
    meta = {r.cells[0].text: r.cells[1].text for r in doc.tables[0].rows}
    assert meta["Registry ID"] == "NCT-SAMPLE-0001"
    assert meta["Sponsor"] == "Sample Therapeutics (fictional)"
    assert meta["Enrollment"] == "120"
    assert meta["Export date"] == "2026-11-09"


def test_visit_schedule_is_a_table_with_one_row_per_visit(sample_plan):
    table = _section_table(_build(sample_plan), "Visit schedule")
    assert [c.text for c in table.rows[0].cells] == ["ID", "Name", "Day", "Window", "Type"]
    assert len(table.rows) == 1 + len(sample_plan["visits"])  # header + 8 visits
    assert [c.text for c in table.rows[3].cells] == ["V3", "Week 2", "Day 15", "±3 days", "Clinic"]


def test_procedures_list_their_visits(sample_plan):
    table = _section_table(_build(sample_plan), "Procedures")
    assert len(table.rows) == 1 + len(sample_plan["procedures"])
    assert _row(table, "Informed consent")["Visits"] == "V1 (Screening)"


def test_only_builtin_styles_are_used(sample_plan):
    doc = _build(sample_plan)
    allowed = {"Title", "Heading 1", "Normal", "List Bullet"}
    assert {p.style.name for p in doc.paragraphs} <= allowed
    assert {t.style.name for t in doc.tables} == {"Table Grid"}


# --- Review status ----------------------------------------------------------

def test_flagged_items_carry_label_and_reason(sample_plan):
    table = _section_table(_build(sample_plan), "Billing")
    with_notes = _row(table, "Spirometry")["Review status"]
    assert with_notes.startswith("FLAGGED – NEEDS REVIEW")
    assert "Reason: Baseline spirometry may be SOC" in with_notes
    assert "Confidence: 55%" in with_notes

    no_notes = _row(table, "Physical exam")["Review status"]
    assert no_notes.startswith("FLAGGED – NEEDS REVIEW")
    assert "below the 70% review threshold" in no_notes


def test_reviewed_items_carry_their_decision(sample_plan):
    doc = _build(sample_plan)
    procs = _section_table(doc, "Procedures")

    edited = _row(procs, "Urine pregnancy test")["Review status"]
    assert edited.startswith("REVIEWED – EDITED")
    assert "By Jane Reviewer on 2026-11-09" in edited
    assert "Comment: SoA table is authoritative" in edited
    # Only the changed field gets a "Was:" line.
    assert "Was: Visits: V2, V3, V4, V5" in edited
    assert "Was: Procedure" not in edited

    rejected = _row(procs, "PK blood sample")["Review status"]
    assert rejected.startswith("REVIEWED – REJECTED")
    assert "Comment: Duplicate of lab draw" in rejected

    accepted = _row(_section_table(doc, "Safety reporting"), "Unanticipated problem")["Review status"]
    assert accepted.startswith("REVIEWED – ACCEPTED")


def test_unflagged_items_say_so(sample_plan):
    status = _row(_section_table(_build(sample_plan), "Procedures"), "Informed consent")["Review status"]
    assert status.startswith("Not flagged")
    assert "FLAGGED" not in status


def test_review_threshold_is_respected(sample_plan):
    # At 0.5 the 0.55 billing item is no longer flagged.
    table = _section_table(_build(sample_plan, review_threshold=0.5), "Billing")
    assert _row(table, "Spirometry")["Review status"].startswith("Not flagged")


def test_section_flag_is_shown_and_flags_its_items(sample_plan):
    sample_plan["section_reviews"] = {"staffing": {"needs_review": True, "reason": "FTEs are estimates"}}
    doc = _build(sample_plan)
    blocks = _section_blocks(doc, "Staffing")
    assert blocks[0].text == "SECTION FLAGGED FOR REVIEW: FTEs are estimates"
    pi = _row(_section_table(doc, "Staffing"), "Principal Investigator")["Review status"]  # 0.85: not low
    assert pi.startswith("FLAGGED – NEEDS REVIEW")
    assert "Section flagged: FTEs are estimates" in pi


def test_review_summary_counts(sample_plan):
    text = "\n".join(p.text for p in _build(sample_plan).paragraphs)
    # 8 low-confidence items in the sample; 3 reviewed -> 5 open.
    assert "Items still flagged for review: 5" in text
    assert "Reviewed: 1 accepted, 1 edited, 1 rejected" in text


# --- Notes, sources, empty sections ----------------------------------------

def test_notes_and_source_pages_appear(sample_plan):
    doc = _build(sample_plan)
    spiro = _row(_section_table(doc, "Procedures"), "Spirometry (FEV1)")["Notes & source"]
    assert "Note: Pre- and post-bronchodilator at V1 only" in spiro
    assert "Source: p. 44" in spiro
    sae = _row(_section_table(doc, "Safety reporting"), "Serious adverse event (SAE)")["Notes & source"]
    assert sae == "Source: p. 57"


def test_empty_category_says_none_found(sample_plan):
    sample_plan["technology"] = []
    sample_plan["pharmacy"] = None
    doc = _build(sample_plan)
    for label in ("Technology", "Pharmacy"):
        texts = [b.text for b in _section_blocks(doc, label) if isinstance(b, Paragraph)]
        assert texts == [NONE_FOUND]


def test_empty_plan_shows_every_section_as_none_found():
    doc = _build({}, reviews={})
    labels = [label for _, label in SECTIONS]
    assert all(label in _headings(doc) for label in labels)
    assert sum(p.text == NONE_FOUND for p in doc.paragraphs) == len(labels)
    meta = {r.cells[0].text: r.cells[1].text for r in doc.tables[0].rows}
    assert meta["Title"] == "Not stated"


def test_pharmacy_involvement_is_stated(sample_plan):
    texts = [b.text for b in _section_blocks(_build(sample_plan), "Pharmacy") if isinstance(b, Paragraph)]
    assert "Investigational pharmacy is involved." in texts


# --- Review keys and filename ----------------------------------------------

@pytest.mark.parametrize("key", ["procedures:99", "visits:0", "nonsense", "safety:-1", "pharmacy:x"])
def test_bad_review_key_is_rejected(sample_plan, key):
    with pytest.raises(ValidationError) as exc:
        DocxExportRequest.model_validate({"plan": sample_plan, "reviews": {key: {"status": "accepted"}}})
    assert key in str(exc.value)


def test_bad_review_status_is_rejected(sample_plan):
    with pytest.raises(ValidationError):
        DocxExportRequest.model_validate({"plan": sample_plan, "reviews": {"safety:2": {"status": "maybe"}}})


def test_filename_uses_short_title_then_registry_id(sample_plan):
    plan = OperationalPlan.model_validate(sample_plan)
    assert export_filename(plan) == "xr-214-asthma-phase-ii-operational-plan.docx"
    plan.protocol.short_title = None
    assert export_filename(plan) == "nct-sample-0001-operational-plan.docx"
    assert export_filename(OperationalPlan()) == "protocol-operational-plan.docx"
