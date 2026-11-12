"""Word (.docx) export of an operational plan, for human review.

The document is a review artifact, not a final plan: it says so up front,
shows every category (even empty ones, so missing data is visible), and marks
each item's review status in plain text so it survives printing and import
into Google Docs. Only built-in Word styles are used (Title, Heading 1,
Normal, List Bullet, Table Grid), with no custom fonts, macros, or embedded
objects.

Review decisions use the frontend's shape (``state.reviews`` in
frontend/app.js, sent as ``Object.fromEntries(state.reviews)``): a mapping of
``"<section>:<index>"`` to ``{status, comment, reviewer, at, original}``. The
frontend applies edits to the plan in place, so the plan already holds the
edited values and ``original`` holds the values from before the edit.

Everything is built in memory; nothing is written to disk.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
from pydantic import BaseModel, Field, model_validator

from models import OperationalPlan

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

# Matches reviewThreshold in frontend/config.js.
DEFAULT_REVIEW_THRESHOLD = 0.7

NONE_FOUND = "None found in protocol."
DRAFT_NOTICE = (
    "AI-GENERATED DRAFT FOR HUMAN REVIEW. This is not a final operational plan. "
    "Every item must be checked against the source protocol before use."
)

# Reading order matches SECTIONS in frontend/app.js.
SECTIONS: List[Tuple[str, str]] = [
    ("visits", "Visit schedule"),
    ("procedures", "Procedures"),
    ("staffing", "Staffing"),
    ("safety", "Safety reporting"),
    ("billing", "Billing"),
    ("equipment", "Equipment"),
    ("pharmacy", "Pharmacy"),
    ("technology", "Technology"),
]
SECTION_LABELS = dict(SECTIONS)

# Sections the frontend lets a reviewer decide on (FIELDS in app.js).
REVIEWABLE = {"procedures", "staffing", "safety", "billing", "equipment", "pharmacy", "technology"}

# Labels for the fields a reviewer can edit, used for "Was:" lines.
FIELD_LABELS = {
    "name": "Procedure", "category": "Category", "visits": "Visits",
    "role": "Role", "fte": "Est. FTE", "responsibilities": "Responsibilities",
    "event": "Event", "timeline": "Timeline", "recipient": "Report to", "method": "Method",
    "item": "Item", "designation": "Designation", "purpose": "Purpose", "system": "System",
}

STATUS_LABELS = {
    "accepted": "REVIEWED – ACCEPTED",
    "edited": "REVIEWED – EDITED",
    "rejected": "REVIEWED – REJECTED",
}
FLAGGED_LABEL = "FLAGGED – NEEDS REVIEW"
NOT_FLAGGED_LABEL = "Not flagged"


# --- Request models ---------------------------------------------------------

class ReviewDecision(BaseModel):
    """One reviewer decision, as stored in the frontend's ``state.reviews``."""

    status: Literal["accepted", "edited", "rejected"]
    comment: Optional[str] = None
    reviewer: Optional[str] = None
    at: Optional[str] = None  # ISO timestamp
    original: Optional[Dict[str, Any]] = None  # field values before an edit
    # Field values after an edit. Needed once plans are stored and shared: the
    # saved plan isn't changed by one reviewer's edit, so the edit travels
    # with the decision and is re-applied when that reviewer opens the plan.
    values: Optional[Dict[str, Any]] = None


class DocxExportRequest(BaseModel):
    """Body of POST /api/export/docx."""

    plan: OperationalPlan
    reviews: Dict[str, ReviewDecision] = Field(default_factory=dict)
    review_threshold: float = Field(default=DEFAULT_REVIEW_THRESHOLD, ge=0.0, le=1.0)
    reviewer: Optional[str] = None
    # Section keys to put first, in this order (the role picker's choice).
    # Sections not listed follow in the standard order. Order only: every
    # section is always included.
    section_order: Optional[List[str]] = None

    @model_validator(mode="after")
    def _check_review_keys(self) -> "DocxExportRequest":
        validate_review_keys(self.plan, self.reviews)
        ordered_sections(self.section_order)  # raises on unknown or repeated keys
        return self


def ordered_sections(first: Optional[List[str]]) -> List[Tuple[str, str]]:
    """All sections, with the requested ones first. Never drops a section."""
    first = first or []
    unknown = [k for k in first if k not in SECTION_LABELS]
    if unknown:
        raise ValueError(f"unknown section(s) in section_order: {', '.join(unknown)}")
    if len(set(first)) != len(first):
        raise ValueError("section_order lists a section more than once")
    rest = [k for k, _ in SECTIONS if k not in first]
    return [(k, SECTION_LABELS[k]) for k in [*first, *rest]]


def items_for(plan: OperationalPlan, key: str) -> list:
    if key == "pharmacy":
        return plan.pharmacy.items if plan.pharmacy else []
    return getattr(plan, key)


def validate_review_keys(plan: OperationalPlan, reviews: Mapping[str, Any]) -> None:
    """Every key must be "<reviewable section>:<index>" naming an existing item."""
    bad = []
    for key in reviews:
        sec, sep, idx = key.partition(":")
        if not sep or sec not in REVIEWABLE or not idx.isdigit():
            bad.append(f"{key!r} is not of the form '<section>:<index>' with a reviewable section")
            continue
        n = len(items_for(plan, sec))
        if int(idx) >= n:
            bad.append(f"{key!r} refers to item {idx}, but {sec} has {n} item(s)")
    if bad:
        raise ValueError("invalid review key(s): " + "; ".join(bad))


def export_slug(plan: OperationalPlan) -> str:
    """Filename stem; same rule as slug() in frontend/app.js."""
    p = plan.protocol
    raw = p.short_title or p.registry_id or "protocol"
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-") or "protocol"


def export_filename(plan: OperationalPlan) -> str:
    return f"{export_slug(plan)}-operational-plan.docx"


# --- Formatting helpers -----------------------------------------------------

def _fmt(value: Any) -> str:
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _fmt_date(at: Optional[str]) -> Optional[str]:
    if not at:
        return None
    try:
        return datetime.fromisoformat(at.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return at


def _pct(conf: float) -> str:
    return f"{round(conf * 100)}%"


Line = Tuple[str, bool]  # (text, bold)


def item_status(
    item: Any,
    decision: Optional[ReviewDecision],
    section_flag_reason: Optional[str],
    threshold: float,
) -> List[Line]:
    """Text lines for an item's review-status cell. First line is the label.

    A reviewer's decision takes precedence over a flag. An item is flagged if
    its confidence is below the threshold or its whole section is flagged.
    """
    conf = getattr(item, "confidence", None)
    low = isinstance(conf, (int, float)) and conf < threshold
    conf_line = [(f"Confidence: {_pct(conf)}", False)] if conf is not None else []

    if decision is not None:
        lines: List[Line] = [(STATUS_LABELS[decision.status], True)]
        who = decision.reviewer or "Reviewer"
        when = _fmt_date(decision.at)
        lines.append((f"By {who}" + (f" on {when}" if when else ""), False))
        if decision.comment:
            lines.append((f"Comment: {decision.comment}", False))
        if decision.status == "edited" and decision.original:
            for field, old in decision.original.items():
                if _fmt(old) != _fmt(getattr(item, field, None)):
                    label = FIELD_LABELS.get(field, field)
                    lines.append((f"Was: {label}: {_fmt(old) if old not in (None, '', []) else '(empty)'}", False))
        return lines + conf_line

    if low or section_flag_reason:
        lines = [(FLAGGED_LABEL, True)]
        if low:
            notes = getattr(item, "notes", None)
            reason = notes or f"confidence is below the {_pct(threshold)} review threshold"
            lines.append((f"Reason: {reason}", False))
        if section_flag_reason:
            lines.append((f"Section flagged: {section_flag_reason}", False))
        return lines + conf_line

    return [(NOT_FLAGGED_LABEL, False)] + conf_line


def is_open_flag(item: Any, decision: Optional[ReviewDecision], section_flag_reason: Optional[str], threshold: float) -> bool:
    return item_status(item, decision, section_flag_reason, threshold)[0][0] == FLAGGED_LABEL


def notes_and_source(item: Any) -> List[Line]:
    lines: List[Line] = []
    notes = getattr(item, "notes", None)
    if notes:
        lines.append((f"Note: {notes}", False))
    page = getattr(item, "source_page", None)
    if page:
        lines.append((f"Source: p. {page}", False))
    return lines or [("—", False)]


# --- docx helpers -----------------------------------------------------------

def _fill(cell, lines: List[Line]) -> None:
    """Write lines into a table cell, one paragraph each."""
    for n, (text, bold) in enumerate(lines):
        para = cell.paragraphs[0] if n == 0 else cell.add_paragraph()
        para.add_run(text).bold = bold


def _repeat_header(row) -> None:
    """Mark a row as a header row that repeats on each page."""
    tr_pr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    tr_pr.append(el)


def _table(doc, headers: List[str], rows: List[List[List[Line]]]):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for cell, h in zip(table.rows[0].cells, headers):
        _fill(cell, [(h, True)])
    _repeat_header(table.rows[0])
    for row in rows:
        cells = table.add_row().cells
        for cell, lines in zip(cells, row):
            _fill(cell, lines)
    return table


def _plain(value: Any) -> List[Line]:
    return [(_fmt(value), False)]


# --- Section column definitions --------------------------------------------

def _visit_label(plan: OperationalPlan):
    names = {v.id: v.name for v in plan.visits}

    def render(ids: List[str]) -> List[Line]:
        if not ids:
            return [("—", False)]
        return [(", ".join(f"{i} ({names[i]})" if names.get(i) else i for i in ids), False)]

    return render


def _columns(plan: OperationalPlan, key: str):
    """(header, renderer) pairs for an item table, before the status/notes columns."""
    visits = _visit_label(plan)
    f = lambda attr: (lambda it: _plain(getattr(it, attr)))  # noqa: E731
    return {
        "procedures": [("Procedure", f("name")), ("Category", f("category")), ("Visits", lambda it: visits(it.visits))],
        "staffing": [("Role", f("role")), ("Est. FTE", f("fte")), ("Responsibilities", f("responsibilities")), ("Qualifications", f("qualifications"))],
        "safety": [("Event", f("event")), ("Timeline", f("timeline")), ("Report to", f("recipient")), ("Method", f("method"))],
        "billing": [("Item", f("item")), ("Designation", f("designation")), ("Visits", lambda it: visits(it.visits))],
        "equipment": [("Item", f("item")), ("Purpose", f("purpose"))],
        "pharmacy": [("Requirement", f("item"))],
        "technology": [("System", f("system")), ("Purpose", f("purpose"))],
    }[key]


# --- Builder ---------------------------------------------------------------

def _coerce_reviews(reviews: Optional[Mapping[str, Any]]) -> Dict[str, ReviewDecision]:
    return {
        k: v if isinstance(v, ReviewDecision) else ReviewDecision.model_validate(v)
        for k, v in (reviews or {}).items()
    }


def build_plan_docx(
    plan: OperationalPlan,
    reviews: Optional[Mapping[str, Any]] = None,
    *,
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
    reviewer: Optional[str] = None,
    export_date: Optional[date] = None,
    section_order: Optional[List[str]] = None,
) -> bytes:
    """Build the review-draft Word document and return it as bytes."""
    decisions = _coerce_reviews(reviews)
    validate_review_keys(plan, decisions)
    export_date = export_date or date.today()
    p = plan.protocol

    def section_reason(key: str) -> Optional[str]:
        flag = getattr(plan.section_reviews, key)
        return flag.reason if flag.needs_review else None

    doc = Document()
    for sec in doc.sections:
        sec.left_margin = sec.right_margin = Inches(0.75)
        sec.footer.paragraphs[0].text = (
            "CORA · AI-generated draft for human review · not a final operational plan"
        )
    props = doc.core_properties
    props.title = f"Operational plan (draft): {p.short_title or p.title or 'protocol'}"
    props.author = "CORA (AI-generated draft)"
    props.comments = "AI-generated draft for human review. Not a final operational plan."

    # Header
    doc.add_paragraph(f"Operational Plan: {p.short_title or p.title or 'Untitled protocol'}", style="Title")
    doc.add_paragraph().add_run(DRAFT_NOTICE).bold = True
    if plan.is_sample:
        doc.add_paragraph("Sample data: generated from a fictional protocol.")

    doc.add_paragraph("Protocol details", style="Heading 1")
    meta = [
        ("Title", p.title), ("Short title", p.short_title), ("Registry ID", p.registry_id),
        ("Phase", p.phase), ("Sponsor", p.sponsor), ("Therapeutic area", p.therapeutic_area),
        ("Design", p.design), ("Enrollment", p.enrollment), ("Duration", p.duration),
        ("Protocol pages", p.pages), ("Extraction method", plan.extraction),
        ("Export date", export_date.isoformat()), ("Reviewer", reviewer),
    ]
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for label, value in meta:
        cells = table.add_row().cells
        _fill(cells[0], [(label, True)])
        _fill(cells[1], [(_fmt(value) if value not in (None, "") else "Not stated", False)])

    # Review summary
    open_flags = 0
    counts = {"accepted": 0, "edited": 0, "rejected": 0}
    for key in REVIEWABLE:
        for i, it in enumerate(items_for(plan, key)):
            d = decisions.get(f"{key}:{i}")
            if d:
                counts[d.status] += 1
            elif is_open_flag(it, None, section_reason(key), review_threshold):
                open_flags += 1

    doc.add_paragraph("Review summary", style="Heading 1")
    if open_flags:
        doc.add_paragraph().add_run(
            f"{open_flags} item(s) still need human review before this plan is used."
        ).bold = True
    doc.add_paragraph(f"Items still flagged for review: {open_flags}", style="List Bullet")
    doc.add_paragraph(
        f"Reviewed: {counts['accepted']} accepted, {counts['edited']} edited, {counts['rejected']} rejected",
        style="List Bullet",
    )
    doc.add_paragraph(
        f"Items with confidence below {_pct(review_threshold)} are flagged for review.",
        style="List Bullet",
    )
    flagged_sections = [(label, section_reason(key)) for key, label in SECTIONS if section_reason(key)]
    if flagged_sections:
        for label, reason in flagged_sections:
            doc.add_paragraph(f"Section flagged – {label}: {reason}", style="List Bullet")
    else:
        doc.add_paragraph("No whole sections are flagged.", style="List Bullet")

    # Categories
    for key, label in ordered_sections(section_order):
        doc.add_paragraph(label, style="Heading 1")
        reason = section_reason(key)
        if reason:
            doc.add_paragraph().add_run(f"SECTION FLAGGED FOR REVIEW: {reason}").bold = True

        if key == "visits":
            if not plan.visits:
                doc.add_paragraph(NONE_FOUND)
                continue
            _table(
                doc,
                ["ID", "Name", "Day", "Window", "Type"],
                [[_plain(v.id), _plain(v.name), _plain(v.day), _plain(v.window), _plain(v.type)] for v in plan.visits],
            )
            continue

        if key == "pharmacy" and plan.pharmacy is not None:
            doc.add_paragraph(
                "Investigational pharmacy is involved."
                if plan.pharmacy.involved
                else "Investigational pharmacy is not involved."
            )

        items = items_for(plan, key)
        if not items:
            doc.add_paragraph(NONE_FOUND)
            continue

        cols = _columns(plan, key)
        rows = []
        for i, it in enumerate(items):
            status = item_status(it, decisions.get(f"{key}:{i}"), reason, review_threshold)
            rows.append([render(it) for _, render in cols] + [status, notes_and_source(it)])
        _table(doc, [h for h, _ in cols] + ["Review status", "Notes & source"], rows)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
