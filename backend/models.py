"""Pydantic models for the CORA operational plan.

This schema is the contract between the backend extraction step (keyword-based
today, LLM-based later) and the frontend that renders the plan. It mirrors the
shape already documented in README.md and sample-data.js, so the existing
frontend consumes validated output with no changes.

Design notes:
- Almost everything is optional. The extraction step (especially the LLM) will
  often fail to find a field; missing data must be representable, never fatal.
- Uncertainty is carried two ways: per-item ``confidence`` (0-1) + ``notes``
  (the model the frontend uses today), and per-section ``ReviewFlag``s in
  ``section_reviews`` (so a whole section can be marked "not extracted / needs
  review"). The system must never present uncertain extractions as certain.
- ``extra`` is left at Pydantic's default ("ignore"): a stray key from the LLM
  is dropped rather than failing the whole plan. The fields that matter are
  still validated (types, ranges, required fields, visit references).
- No patient-level or personally identifiable data: study operations only.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class ReviewFlag(BaseModel):
    """Marks a section as uncertain or incomplete, with a short reason.

    Hard requirement: if ``needs_review`` is True, ``reason`` must explain why,
    so the system never presents an uncertain section as certain.
    """

    needs_review: bool = False
    reason: Optional[str] = None

    @model_validator(mode="after")
    def _reason_required_when_flagged(self) -> "ReviewFlag":
        if self.needs_review and not (self.reason and self.reason.strip()):
            raise ValueError("reason is required when needs_review is True")
        return self


class ProtocolMetadata(BaseModel):
    """Study-level metadata from the protocol's title page."""

    title: Optional[str] = None
    short_title: Optional[str] = None
    registry_id: Optional[str] = None  # NCT number, when present
    phase: Optional[str] = None
    sponsor: Optional[str] = None
    therapeutic_area: Optional[str] = None
    design: Optional[str] = None
    enrollment: Optional[int] = Field(default=None, ge=0)
    duration: Optional[str] = None
    pages: Optional[int] = Field(default=None, ge=0)


class Visit(BaseModel):
    """One scheduled visit. ``id`` is referenced by procedure/billing visit tags.

    Timing is kept as free text (``day`` / ``window``) because protocols phrase
    it many ways ("Day 1", "Week 4", "Day -28 to -1", "±3 days"). The activities
    performed at each visit are represented by procedures tagged with this
    visit's ``id`` (the Schedule-of-Activities matrix), not duplicated here.
    """

    id: str
    name: Optional[str] = None
    day: Optional[str] = None     # e.g. "Day 1", "Day -28 to -1"
    window: Optional[str] = None  # e.g. "±3 days"
    type: Optional[str] = None    # e.g. "Clinic", "Phone" (free text label)


class Procedure(BaseModel):
    """A required study procedure, tagged with the visits where it occurs."""

    name: str
    category: Optional[str] = None
    visits: List[str] = Field(default_factory=list)  # Visit.id values
    notes: Optional[str] = None
    source_page: Optional[int] = Field(default=None, ge=1)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class StaffingRole(BaseModel):
    """A required role, with any stated qualifications or certifications."""

    role: str
    fte: Optional[float] = Field(default=None, ge=0.0)
    responsibilities: Optional[str] = None
    qualifications: Optional[str] = None  # stated certs / qualifications, if any
    notes: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class SafetyReport(BaseModel):
    """A safety-reporting obligation, including AE reporting timelines."""

    event: str
    timeline: Optional[str] = None   # e.g. "Within 24 hours of awareness"
    recipient: Optional[str] = None
    method: Optional[str] = None
    notes: Optional[str] = None
    source_page: Optional[int] = Field(default=None, ge=1)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


# --- Later sections: already part of the documented contract and rendered by
# --- the frontend, but not a focus of this issue. Included so the model is a
# --- faithful contract; left lightly specified for now.

class BillingItem(BaseModel):
    item: str
    designation: Optional[str] = None  # e.g. "Sponsor", "Standard of care"
    visits: List[str] = Field(default_factory=list)  # Visit.id values
    notes: Optional[str] = None
    source_page: Optional[int] = Field(default=None, ge=1)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class EquipmentItem(BaseModel):
    item: str
    purpose: Optional[str] = None
    notes: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class TechnologyItem(BaseModel):
    system: str
    purpose: Optional[str] = None
    notes: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class PharmacyItem(BaseModel):
    item: str
    notes: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class Pharmacy(BaseModel):
    involved: bool = False
    items: List[PharmacyItem] = Field(default_factory=list)


class SectionReviews(BaseModel):
    """Per-section uncertainty flags. Every section carries its own ReviewFlag,
    each defaulting to "not flagged" so an omitted entry is treated as certain
    only when extraction actually succeeded."""

    visits: ReviewFlag = Field(default_factory=ReviewFlag)
    procedures: ReviewFlag = Field(default_factory=ReviewFlag)
    safety: ReviewFlag = Field(default_factory=ReviewFlag)
    staffing: ReviewFlag = Field(default_factory=ReviewFlag)
    # later sections
    billing: ReviewFlag = Field(default_factory=ReviewFlag)
    equipment: ReviewFlag = Field(default_factory=ReviewFlag)
    pharmacy: ReviewFlag = Field(default_factory=ReviewFlag)
    technology: ReviewFlag = Field(default_factory=ReviewFlag)


class OperationalPlan(BaseModel):
    """Top-level operational plan: protocol metadata plus every section.

    This is the object the backend returns from POST /api/protocols and the
    frontend renders.
    """

    id: Optional[str] = None
    is_sample: bool = False
    extraction: Optional[str] = None  # e.g. "keyword", "llm"

    protocol: ProtocolMetadata = Field(default_factory=ProtocolMetadata)

    # Definite sections for this issue.
    visits: List[Visit] = Field(default_factory=list)
    procedures: List[Procedure] = Field(default_factory=list)
    staffing: List[StaffingRole] = Field(default_factory=list)
    safety: List[SafetyReport] = Field(default_factory=list)

    # Later sections (already rendered by the frontend; not built out here).
    billing: List[BillingItem] = Field(default_factory=list)
    equipment: List[EquipmentItem] = Field(default_factory=list)
    pharmacy: Optional[Pharmacy] = None
    technology: List[TechnologyItem] = Field(default_factory=list)

    section_reviews: SectionReviews = Field(default_factory=SectionReviews)

    @model_validator(mode="after")
    def _check_visit_references(self) -> "OperationalPlan":
        """Visit ids must be unique, and every procedure/billing visit tag must
        refer to a visit that exists in the schedule."""
        ids = [v.id for v in self.visits]

        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate visit id(s): {', '.join(duplicates)}")

        known = set(ids)
        bad: List[str] = []
        for proc in self.procedures:
            for tag in proc.visits:
                if tag not in known:
                    bad.append(f"procedure {proc.name!r} -> {tag!r}")
        for bill in self.billing:
            for tag in bill.visits:
                if tag not in known:
                    bad.append(f"billing {bill.item!r} -> {tag!r}")
        if bad:
            raise ValueError(
                "visit tag(s) refer to unknown visits: " + "; ".join(bad)
            )
        return self
