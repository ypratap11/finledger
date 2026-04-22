"""revrec usage_events

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("obligation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("revrec.performance_obligations.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("units", sa.BigInteger, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("inbox.source_events.id"), nullable=True),
        sa.Column("recognized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recognition_run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("revrec.recognition_runs.id"), nullable=True),
        sa.CheckConstraint("units > 0", name="ck_usage_events_units_positive"),
        sa.CheckConstraint("source IN ('api', 'zuora')", name="ck_usage_events_source"),
        schema="revrec",
    )
    op.create_index(
        "ix_usage_events_obligation", "usage_events", ["obligation_id"], schema="revrec"
    )
    op.create_index(
        "ix_usage_events_pending",
        "usage_events", ["obligation_id"],
        schema="revrec",
        postgresql_where=sa.text("recognized_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_usage_events_pending", table_name="usage_events", schema="revrec")
    op.drop_index("ix_usage_events_obligation", table_name="usage_events", schema="revrec")
    op.drop_table("usage_events", schema="revrec")
