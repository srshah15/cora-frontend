"""Create protocols, plans and reviews.

Revision ID: 0001
Revises:
Create Date: 2026-11-11

No table has a column for PDF bytes or raw protocol text (issue #25).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# JSONB on Postgres, JSON on anything else (SQLite in tests).
Json = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "protocols",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("nct_id", sa.String(32)),
        sa.Column("protocol_number", sa.String(128)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("content_hash"),
    )
    op.create_index("ix_protocols_nct_id", "protocols", ["nct_id"])
    op.create_index("ix_protocols_protocol_number", "protocols", ["protocol_number"])

    op.create_table(
        "plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("protocol_id", sa.String(36), sa.ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_json", Json, nullable=False),
        sa.Column("extraction_method", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("protocol_id"),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("reviewer_name", sa.String(100)),
        sa.Column("item_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("values", Json),
        sa.Column("original", Json),
        sa.Column("decided_at", sa.String(40)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("plan_id", "reviewer_id", "item_key", name="uq_review_plan_reviewer_item"),
    )
    op.create_index("ix_reviews_plan_id", "reviews", ["plan_id"])
    op.create_index("ix_reviews_reviewer_id", "reviews", ["reviewer_id"])


def downgrade() -> None:
    op.drop_table("reviews")
    op.drop_table("plans")
    op.drop_table("protocols")
