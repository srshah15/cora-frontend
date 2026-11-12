"""The shape Claude is asked to fill in (structured output).

This is deliberately separate from models.py:
- models.py is the strict contract with the frontend (ranges, visit references).
- These models are loose on purpose. Every field is present but may be null,
  and numbers carry no range limits, because the API's JSON-schema mode doesn't
  enforce ranges anyway. llm_extractor.py then checks each item against the
  strict models, so one bad item can be dropped without losing the whole plan.

The field descriptions are sent to the model as part of the schema, so they
double as instructions.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

_PAGE = Field(description="Page number from the <page n=...> tag where this is stated. null if unsure.")
_CONF = Field(description="0 to 1. How sure you are that the protocol states this. Below 0.7 means a human must check it.")
_NOTES = Field(description="Why this is uncertain or incomplete, or null. Required when confidence is below 0.7.")


class LLMHeader(BaseModel):
    title: Optional[str] = Field(description="Full protocol title, or null.")
    short_title: Optional[str] = Field(description="Short title or acronym stated in the protocol, or null.")
    protocol_number: Optional[str] = Field(description="The sponsor's protocol number or identifier exactly as written (not the NCT number). null if not stated.")
    phase: Optional[str] = Field(description='e.g. "Phase 2". null if not stated.')
    sponsor: Optional[str]
    therapeutic_area: Optional[str]
    design: Optional[str] = Field(description="Study design as stated, e.g. randomized, double-blind.")
    enrollment: Optional[int] = Field(description="Planned total enrollment. null if not stated.")
    duration: Optional[str] = Field(description="Per-participant or study duration as stated.")


class LLMVisit(BaseModel):
    id: str = Field(description='Short unique id you assign in schedule order: "V1", "V2", ... Use "ET" or "UNS" for early termination or unscheduled visits.')
    name: Optional[str] = Field(description="Visit name as written in the protocol.")
    day: Optional[str] = Field(description='Timing as written, e.g. "Day 1", "Week 4", "Day -28 to -1".')
    window: Optional[str] = Field(description='Allowed window as written, e.g. "±3 days". null if none stated.')
    type: Optional[str] = Field(description='"Clinic", "Phone", "Remote", or as stated. null if not stated.')
    source_page: Optional[int] = _PAGE
    confidence: Optional[float] = _CONF
    notes: Optional[str] = _NOTES


class LLMProcedure(BaseModel):
    name: str
    category: Optional[str] = Field(description='e.g. "Lab", "Clinical", "Imaging", "Regulatory", "Safety".')
    visits: List[str] = Field(description="ids of the visits (from the visits list) where this procedure is required. Empty if the protocol doesn't say.")
    source_page: Optional[int] = _PAGE
    confidence: Optional[float] = _CONF
    notes: Optional[str] = _NOTES


class LLMStaffing(BaseModel):
    role: str = Field(description="A role the protocol says is needed, e.g. Principal Investigator, unblinded pharmacist.")
    fte: Optional[float] = Field(description="Effort in FTE ONLY if the protocol states a number. Otherwise null. Never estimate.")
    responsibilities: Optional[str] = Field(description="What the protocol says this role does.")
    qualifications: Optional[str] = Field(description="Qualifications, licences, training or certifications the protocol requires for this role. null if none stated.")
    source_page: Optional[int] = _PAGE
    confidence: Optional[float] = _CONF
    notes: Optional[str] = _NOTES


class LLMSafety(BaseModel):
    event: str = Field(description="What must be reported, e.g. Serious adverse event (SAE), pregnancy.")
    timeline: Optional[str] = Field(description='Reporting deadline as written, e.g. "Within 24 hours of awareness".')
    recipient: Optional[str] = Field(description="Who it is reported to.")
    method: Optional[str] = Field(description="How it is reported, e.g. SAE form in EDC.")
    source_page: Optional[int] = _PAGE
    confidence: Optional[float] = _CONF
    notes: Optional[str] = _NOTES


class LLMBilling(BaseModel):
    item: str = Field(description="A procedure or service with a stated payer.")
    designation: Optional[str] = Field(description='"Sponsor", "Standard of care", or as stated. null if the protocol doesn\'t say who pays.')
    visits: List[str] = Field(description="Visit ids where this applies. Empty if not stated.")
    source_page: Optional[int] = _PAGE
    confidence: Optional[float] = _CONF
    notes: Optional[str] = _NOTES


class LLMEquipment(BaseModel):
    item: str
    purpose: Optional[str]
    source_page: Optional[int] = _PAGE
    confidence: Optional[float] = _CONF
    notes: Optional[str] = _NOTES


class LLMPharmacyItem(BaseModel):
    item: str = Field(description="A pharmacy requirement: storage, preparation, accountability, blinding.")
    source_page: Optional[int] = _PAGE
    confidence: Optional[float] = _CONF
    notes: Optional[str] = _NOTES


class LLMTechnology(BaseModel):
    system: str = Field(description="A system sites must use, e.g. EDC, IRT/IWRS, ePRO.")
    purpose: Optional[str]
    source_page: Optional[int] = _PAGE
    confidence: Optional[float] = _CONF
    notes: Optional[str] = _NOTES


class LLMPlan(BaseModel):
    protocol: LLMHeader
    # The minimum-success categories.
    visits: List[LLMVisit]
    procedures: List[LLMProcedure]
    staffing: List[LLMStaffing]
    # The remaining categories.
    safety: List[LLMSafety]
    billing: List[LLMBilling]
    equipment: List[LLMEquipment]
    pharmacy_involved: Optional[bool] = Field(description="true if an investigational pharmacy handles study product, false if the protocol makes clear none is needed, null if unclear.")
    pharmacy_items: List[LLMPharmacyItem]
    technology: List[LLMTechnology]
