"""Unit tests for the CORA operational-plan schema (backend/models.py)."""

import pytest
from pydantic import ValidationError

from models import OperationalPlan, ReviewFlag


def _full_plan() -> dict:
    """A valid, fully-populated plan mirroring the shape of sample-data.js."""
    return {
        "id": "sample",
        "is_sample": True,
        "extraction": "llm",
        "protocol": {
            "title": "A Phase II Study of XR-214 in Moderate Persistent Asthma",
            "short_title": "XR-214 Asthma Phase II",
            "registry_id": "NCT-SAMPLE-0001",
            "phase": "Phase II",
            "sponsor": "Sample Therapeutics (fictional)",
            "therapeutic_area": "Pulmonology",
            "design": "Randomized 1:1, double-blind, placebo-controlled",
            "enrollment": 120,
            "duration": "16 weeks per participant",
            "pages": 87,
        },
        "visits": [
            {"id": "V1", "name": "Screening", "day": "Day -28 to -1", "window": None, "type": "Clinic"},
            {"id": "V2", "name": "Baseline", "day": "Day 1", "window": None, "type": "Clinic"},
            {"id": "V3", "name": "Week 4", "day": "Day 29", "window": "±3 days", "type": "Clinic"},
            {"id": "ET", "name": "Early Termination", "day": "As needed", "window": None, "type": "Clinic"},
        ],
        "procedures": [
            {"name": "Informed consent", "category": "Regulatory", "visits": ["V1"], "source_page": 34, "confidence": 0.98},
            {"name": "Vital signs", "category": "Clinical", "visits": ["V1", "V2", "V3", "ET"], "source_page": 42, "confidence": 0.96},
            {"name": "PK blood sample", "category": "Lab", "visits": ["V2"], "source_page": 48, "confidence": 0.58, "notes": "Timing relative to dose unclear"},
        ],
        "staffing": [
            {"role": "Principal Investigator", "fte": 0.1, "responsibilities": "Oversight, AE causality", "confidence": 0.85},
            {"role": "Research Nurse", "fte": 0.3, "responsibilities": "Vitals, blood draws", "qualifications": "RN, GCP-certified", "confidence": 0.74},
        ],
        "safety": [
            {"event": "Serious adverse event (SAE)", "timeline": "Within 24 hours of awareness", "recipient": "Sponsor safety desk", "method": "EDC + fax backup", "source_page": 57, "confidence": 0.96},
        ],
        "billing": [
            {"item": "Screening labs", "designation": "Sponsor", "visits": ["V1"], "confidence": 0.84},
        ],
        "equipment": [
            {"item": "Calibrated spirometer", "purpose": "FEV1 measurements", "confidence": 0.92},
        ],
        "pharmacy": {
            "involved": True,
            "items": [{"item": "Blinded IP storage at 2-8 C", "confidence": 0.9}],
        },
        "technology": [
            {"system": "EDC", "purpose": "Case report forms", "confidence": 0.93},
        ],
    }


# --- Acceptance cases -------------------------------------------------------

def test_valid_full_plan_accepted():
    plan = OperationalPlan.model_validate(_full_plan())
    assert plan.protocol.registry_id == "NCT-SAMPLE-0001"
    assert len(plan.visits) == 4
    assert plan.procedures[1].visits == ["V1", "V2", "V3", "ET"]
    assert plan.staffing[1].qualifications == "RN, GCP-certified"
    # Sections default to not-flagged when section_reviews is omitted.
    assert plan.section_reviews.visits.needs_review is False


def test_minimal_plan_with_missing_optional_fields_accepted():
    # Extraction found very little: just a title and one untagged procedure.
    data = {
        "protocol": {"title": "Some protocol"},
        "procedures": [{"name": "Adverse event assessment"}],  # no visits/confidence/notes
    }
    plan = OperationalPlan.model_validate(data)
    assert plan.protocol.title == "Some protocol"
    assert plan.protocol.registry_id is None
    assert plan.visits == []
    assert plan.procedures[0].visits == []
    assert plan.procedures[0].confidence is None
    assert plan.pharmacy is None


def test_section_can_be_flagged_for_review():
    # Keyword-mode reality: some sections are not extracted yet and must be
    # flagged with a reason rather than silently presented as empty-but-certain.
    data = {
        "protocol": {"title": "Keyword-mode draft"},
        "section_reviews": {
            "visits": {"needs_review": True, "reason": "Visit schedule not extracted yet"},
            "staffing": {"needs_review": True, "reason": "Staffing not extracted yet"},
        },
    }
    plan = OperationalPlan.model_validate(data)
    assert plan.section_reviews.visits.needs_review is True
    assert plan.section_reviews.visits.reason == "Visit schedule not extracted yet"
    assert plan.section_reviews.procedures.needs_review is False  # default


def test_empty_plan_is_accepted():
    # Nothing but defaults — the extraction step may legitimately find nothing.
    plan = OperationalPlan()
    assert plan.protocol.title is None
    assert plan.procedures == []


# --- Rejection cases --------------------------------------------------------

def test_flag_without_reason_is_rejected():
    with pytest.raises(ValidationError):
        ReviewFlag(needs_review=True)
    with pytest.raises(ValidationError):
        ReviewFlag(needs_review=True, reason="   ")  # blank reason doesn't count


def test_confidence_out_of_range_is_rejected():
    data = _full_plan()
    data["procedures"][0]["confidence"] = 1.5  # must be 0-1
    with pytest.raises(ValidationError):
        OperationalPlan.model_validate(data)


def test_missing_required_field_is_rejected():
    data = _full_plan()
    del data["procedures"][0]["name"]  # name is required
    with pytest.raises(ValidationError):
        OperationalPlan.model_validate(data)


def test_wrong_type_is_rejected():
    data = _full_plan()
    data["protocol"]["enrollment"] = "one hundred"  # not an int
    with pytest.raises(ValidationError):
        OperationalPlan.model_validate(data)


def test_procedure_tagged_to_nonexistent_visit_is_rejected():
    data = _full_plan()
    data["procedures"][0]["visits"] = ["V1", "V99"]  # V99 is not in the schedule
    with pytest.raises(ValidationError) as exc:
        OperationalPlan.model_validate(data)
    assert "V99" in str(exc.value)


def test_billing_tagged_to_nonexistent_visit_is_rejected():
    data = _full_plan()
    data["billing"][0]["visits"] = ["V404"]
    with pytest.raises(ValidationError) as exc:
        OperationalPlan.model_validate(data)
    assert "V404" in str(exc.value)


def test_duplicate_visit_ids_are_rejected():
    data = _full_plan()
    data["visits"].append({"id": "V1", "name": "Accidental duplicate"})
    with pytest.raises(ValidationError) as exc:
        OperationalPlan.model_validate(data)
    assert "V1" in str(exc.value)
