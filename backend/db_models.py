"""Database tables (SQLAlchemy ORM).

An ORM maps Python classes to tables: each class below is a table, each
attribute a column, and an instance is one row.

Three tables:
- protocols: which document this is. Identification only, never its content.
- plans:     the extracted operational plan (JSON), one per protocol.
- reviews:   one reviewer's decision on one item of one plan.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSONB on Postgres (indexable, compact); plain JSON elsewhere (SQLite in tests).
JsonType = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Protocol(Base):
    __tablename__ = "protocols"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # SHA-256 of the uploaded bytes, as 64 hex characters. A hash identifies
    # the exact file without storing it, and can't be turned back into it.
    # UNIQUE makes the database itself refuse a second row for the same file.
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    nct_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    protocol_number: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    # 1 for the first file of a study; a different file with the same NCT id
    # or protocol number gets the next number.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    plan: Mapped["Plan"] = relationship(back_populates="protocol", uselist=False, cascade="all, delete-orphan")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    protocol_id: Mapped[str] = mapped_column(ForeignKey("protocols.id", ondelete="CASCADE"), unique=True, nullable=False)
    # The OperationalPlan as JSON: extracted items only, not protocol text.
    plan_json: Mapped[Any] = mapped_column(JsonType, nullable=False)
    extraction_method: Mapped[Optional[str]] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    protocol: Mapped[Protocol] = relationship(back_populates="plan")
    reviews: Mapped[list["Review"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class Review(Base):
    __tablename__ = "reviews"
    # One decision per reviewer per item. Saving again updates that row, and
    # no query without reviewer_id can ever touch it.
    __table_args__ = (UniqueConstraint("plan_id", "reviewer_id", "item_key", name="uq_review_plan_reviewer_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    # Random id the browser made once. It separates reviewers; it is NOT
    # authentication (see README).
    reviewer_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reviewer_name: Mapped[Optional[str]] = mapped_column(String(100))
    item_key: Mapped[str] = mapped_column(String(64), nullable=False)  # "<section>:<index>"
    status: Mapped[str] = mapped_column(String(16), nullable=False)    # accepted | edited | rejected
    comment: Mapped[Optional[str]] = mapped_column(Text)
    # For an edit: the reviewer's new field values, and the values before.
    # The stored plan itself is never changed by one reviewer's edit.
    values: Mapped[Optional[Any]] = mapped_column(JsonType)
    original: Mapped[Optional[Any]] = mapped_column(JsonType)
    decided_at: Mapped[Optional[str]] = mapped_column(String(40))  # ISO timestamp from the browser
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    plan: Mapped[Plan] = relationship(back_populates="reviews")
