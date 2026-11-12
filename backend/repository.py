"""All database reads and writes, in one place.

Rule enforced here (issue #26): plans are shared, review decisions are private.
Every function that touches reviews takes a reviewer_id and filters on it, so
one reviewer can't read, overwrite or delete another's decisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db_models import Plan, Protocol, Review
from docx_export import ReviewDecision
from models import OperationalPlan

NCT = re.compile(r"^NCT\d{8}$", re.I)


@dataclass
class Stored:
    plan_id: str
    version: int
    plan_json: dict
    extraction_method: Optional[str]


def _stored(plan: Plan) -> Stored:
    return Stored(plan.id, plan.protocol.version, plan.plan_json, plan.extraction_method)


def identifiers(plan: OperationalPlan) -> tuple:
    """(nct_id, protocol_number) for matching versions of the same study."""
    reg = (plan.protocol.registry_id or "").strip()
    nct = reg.upper() if NCT.match(reg) else None
    number = (plan.protocol.protocol_number or "").strip() or None
    if number is None and reg and not nct:
        number = reg  # older plans put the protocol number in registry_id
    return nct, number


def find_by_hash(session: Session, content_hash: str) -> Optional[Stored]:
    plan = session.scalar(select(Plan).join(Protocol).where(Protocol.content_hash == content_hash))
    return _stored(plan) if plan else None


def _next_version(session: Session, nct: Optional[str], number: Optional[str]) -> int:
    """1 for a new study; otherwise one more than the newest stored version."""
    same_study = [c for c in (Protocol.nct_id == nct if nct else None,
                              Protocol.protocol_number == number if number else None) if c is not None]
    if not same_study:
        return 1
    newest = session.scalar(select(func.max(Protocol.version)).where(or_(*same_study)))
    return (newest or 0) + 1


def save_plan(session: Session, content_hash: str, plan: OperationalPlan) -> Stored:
    """Store a new protocol and its plan. Safe if two uploads race."""
    nct, number = identifiers(plan)
    protocol = Protocol(
        content_hash=content_hash,
        nct_id=nct,
        protocol_number=number,
        version=_next_version(session, nct, number),
        title=plan.protocol.title,
    )
    protocol.plan = Plan(plan_json=plan.model_dump(mode="json"), extraction_method=plan.extraction)
    session.add(protocol)
    try:
        session.flush()  # sends the INSERT now, so a duplicate hash fails here
    except IntegrityError:
        # Another request stored the same file a moment ago. The UNIQUE
        # constraint stopped our insert; use the row that won.
        session.rollback()
        existing = find_by_hash(session, content_hash)
        if existing is None:
            raise
        return existing
    return _stored(protocol.plan)


def replace_plan(session: Session, plan_id: str, plan: OperationalPlan) -> Stored:
    """Swap a stored keyword-only plan for a better (LLM) one.

    Review keys are positions in the old plan, so they can't carry over;
    reviews of the replaced plan are removed.
    """
    row = session.get(Plan, plan_id)
    for review in list(row.reviews):
        session.delete(review)
    row.plan_json = plan.model_dump(mode="json")
    row.extraction_method = plan.extraction
    row.protocol.title = plan.protocol.title
    session.flush()
    return _stored(row)


def get_plan(session: Session, plan_id: str) -> Optional[Stored]:
    plan = session.get(Plan, plan_id)
    return _stored(plan) if plan else None


def _to_decision(r: Review) -> ReviewDecision:
    return ReviewDecision(
        status=r.status, comment=r.comment, reviewer=r.reviewer_name, at=r.decided_at,
        original=r.original, values=r.values,
    )


def reviews_for(session: Session, plan_id: str, reviewer_id: str) -> Dict[str, ReviewDecision]:
    """This reviewer's decisions on this plan, and nobody else's."""
    rows = session.scalars(
        select(Review).where(Review.plan_id == plan_id, Review.reviewer_id == reviewer_id).order_by(Review.id)
    )
    return {r.item_key: _to_decision(r) for r in rows}


def other_reviewer_count(session: Session, plan_id: str, reviewer_id: str) -> int:
    """How many *other* people have reviewed this plan. A count, never who or what."""
    return session.scalar(
        select(func.count(func.distinct(Review.reviewer_id))).where(
            Review.plan_id == plan_id, Review.reviewer_id != reviewer_id
        )
    ) or 0


def upsert_review(
    session: Session, plan_id: str, reviewer_id: str, reviewer_name: Optional[str],
    item_key: str, decision: ReviewDecision,
) -> ReviewDecision:
    """Insert this reviewer's decision for the item, or update their existing one."""
    row = session.scalar(
        select(Review).where(
            Review.plan_id == plan_id, Review.reviewer_id == reviewer_id, Review.item_key == item_key
        )
    )
    if row is None:
        row = Review(plan_id=plan_id, reviewer_id=reviewer_id, item_key=item_key, status=decision.status)
        session.add(row)
    row.status = decision.status
    row.comment = decision.comment
    row.reviewer_name = reviewer_name or decision.reviewer
    row.values = decision.values
    row.original = decision.original
    row.decided_at = decision.at
    session.flush()
    return _to_decision(row)


def delete_reviews(session: Session, plan_id: str, reviewer_id: str, item_key: Optional[str] = None) -> int:
    """Remove this reviewer's decisions on a plan (all, or one item). Returns how many."""
    query = select(Review).where(Review.plan_id == plan_id, Review.reviewer_id == reviewer_id)
    if item_key is not None:
        query = query.where(Review.item_key == item_key)
    rows = list(session.scalars(query))
    for row in rows:
        session.delete(row)
    session.flush()
    return len(rows)


def list_plans(session: Session, reviewer_id: str) -> List[dict]:
    """Every stored plan, newest first, with review counts for this reviewer."""
    out = []
    for plan in session.scalars(select(Plan).join(Protocol).order_by(Protocol.created_at.desc(), Plan.id)):
        p = plan.protocol
        header = (plan.plan_json or {}).get("protocol") or {}
        mine = session.scalar(
            select(func.count()).select_from(Review).where(
                Review.plan_id == plan.id, Review.reviewer_id == reviewer_id
            )
        ) or 0
        out.append({
            "id": plan.id,
            "title": p.title,
            "short_title": header.get("short_title"),
            "nct_id": p.nct_id,
            "protocol_number": p.protocol_number,
            "version": p.version,
            "extraction": plan.extraction_method,
            "created_at": p.created_at,
            "my_review_count": mine,
            "other_reviewer_count": other_reviewer_count(session, plan.id, reviewer_id),
        })
    return out
