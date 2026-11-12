"""Request and response bodies for the persistence endpoints (issues #26, #27).

Every body is a Pydantic model, so FastAPI validates what comes in and what
goes out.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from docx_export import ReviewDecision
from models import OperationalPlan


class ProtocolResponse(OperationalPlan):
    """What POST /api/protocols returns: the plan, plus storage details.

    It extends OperationalPlan, so every existing field is where clients
    already expect it. The extra fields are optional and stay at their
    defaults when persistence is off.
    """

    plan_id: Optional[str] = None  # id of the stored plan; None if nothing was stored
    reused: bool = False           # True when this exact file was uploaded before
    version: Optional[int] = None  # version number among files of the same study
    # The caller's own saved decisions (empty for a new plan or a new reviewer).
    reviews: Dict[str, ReviewDecision] = Field(default_factory=dict)


class PlanSummary(BaseModel):
    id: str
    title: Optional[str] = None
    short_title: Optional[str] = None
    nct_id: Optional[str] = None
    protocol_number: Optional[str] = None
    version: int
    extraction: Optional[str] = None
    created_at: Optional[datetime] = None
    my_review_count: int = 0
    other_reviewer_count: int = 0


class PlanList(BaseModel):
    plans: List[PlanSummary]


class PlanDetail(BaseModel):
    plan_id: str
    version: int
    plan: OperationalPlan
    reviews: Dict[str, ReviewDecision] = Field(default_factory=dict)  # the caller's only
    other_reviewer_count: int = 0


class Deleted(BaseModel):
    deleted: int
