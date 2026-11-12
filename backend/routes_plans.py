"""Endpoints for saved plans and review decisions (issue #26).

Reviewer identity comes from two headers the browser sends:
  X-Reviewer-Id:   a random UUID the browser created once
  X-Reviewer-Name: the display name typed in the review screen (URL-encoded)

This is NOT authentication. Anyone who sends someone else's id can read and
change that person's decisions. It only keeps honest reviewers' work apart.
"""

from __future__ import annotations

import uuid
from typing import Iterator, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

import db
import repository as repo
from api_models import Deleted, PlanDetail, PlanList, PlanSummary
from docx_export import ReviewDecision, validate_review_keys
from models import OperationalPlan

router = APIRouter(prefix="/api/plans", tags=["plans"])

NOT_CONFIGURED = "Saving isn't configured on this server (DATABASE_URL is not set)."


def parse_reviewer_id(value: Optional[str]) -> Optional[str]:
    """Return the id in canonical form, or raise 400 if it isn't a UUID."""
    if value is None or not value.strip():
        return None
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Reviewer-Id must be a UUID.")


def parse_reviewer_name(value: Optional[str]) -> Optional[str]:
    # HTTP headers can't carry non-ASCII text directly, so the browser
    # URL-encodes the name.
    name = unquote(value or "").strip()
    return name[:100] or None


def reviewer_id(x_reviewer_id: Optional[str] = Header(default=None)) -> str:
    rid = parse_reviewer_id(x_reviewer_id)
    if rid is None:
        raise HTTPException(status_code=400, detail="The X-Reviewer-Id header is required.")
    return rid


def reviewer_name(x_reviewer_name: Optional[str] = Header(default=None)) -> Optional[str]:
    return parse_reviewer_name(x_reviewer_name)


def session() -> Iterator[Session]:
    if not db.is_configured():
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    with db.session_scope() as s:
        yield s


def _plan_or_404(s: Session, plan_id: str) -> repo.Stored:
    stored = repo.get_plan(s, plan_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="No saved plan has that id.")
    return stored


@router.get("", response_model=PlanList)
def list_plans(rid: str = Depends(reviewer_id), s: Session = Depends(session)):
    """All saved plans. Plans are shared; the counts are specific to the caller."""
    return PlanList(plans=[PlanSummary(**row) for row in repo.list_plans(s, rid)])


@router.get("/{plan_id}", response_model=PlanDetail)
def get_plan(plan_id: str, rid: str = Depends(reviewer_id), s: Session = Depends(session)):
    """A saved plan, the caller's own decisions, and how many others reviewed it."""
    stored = _plan_or_404(s, plan_id)
    return PlanDetail(
        plan_id=stored.plan_id,
        version=stored.version,
        plan=OperationalPlan.model_validate(stored.plan_json),
        reviews=repo.reviews_for(s, plan_id, rid),
        other_reviewer_count=repo.other_reviewer_count(s, plan_id, rid),
    )


@router.put("/{plan_id}/reviews/{item_key}", response_model=ReviewDecision)
def save_review(
    plan_id: str,
    item_key: str,
    decision: ReviewDecision,
    rid: str = Depends(reviewer_id),
    name: Optional[str] = Depends(reviewer_name),
    s: Session = Depends(session),
):
    """Save the caller's decision on one item (creates or replaces their own)."""
    stored = _plan_or_404(s, plan_id)
    try:
        # Same rule as the Word export: "<section>:<index>" naming a real item.
        validate_review_keys(OperationalPlan.model_validate(stored.plan_json), {item_key: decision})
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return repo.upsert_review(s, plan_id, rid, name, item_key, decision)


@router.delete("/{plan_id}", response_model=Deleted)
def remove_reviewer_from_plan(plan_id: str, rid: str = Depends(reviewer_id), s: Session = Depends(session)):
    """Remove the caller from a plan: delete all of their decisions on it.

    The plan itself and other reviewers' decisions are untouched.
    """
    _plan_or_404(s, plan_id)
    return Deleted(deleted=repo.delete_reviews(s, plan_id, rid))


@router.delete("/{plan_id}/reviews/{item_key}", response_model=Deleted)
def undo_review(plan_id: str, item_key: str, rid: str = Depends(reviewer_id), s: Session = Depends(session)):
    """Undo the caller's decision on one item (the UI's "Undo decision")."""
    _plan_or_404(s, plan_id)
    return Deleted(deleted=repo.delete_reviews(s, plan_id, rid, item_key))
