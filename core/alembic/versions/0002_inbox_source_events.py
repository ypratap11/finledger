"""inbox.source_events

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("prev_hash", postgresql.BYTEA, nullable=False),
        sa.Column("row_hash", postgresql.BYTEA, nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_error", sa.Text, nullable=True),
        sa.UniqueConstraint("source", "external_id", name="uq_source_external"),
        schema="inbox",
    )
    op.create_index("ix_source_events_unprocessed", "source_events", ["received_at"],
                    schema="inbox", postgresql_where=sa.text("processed_at IS NULL"))
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')


def downgrade() -> None:
    op.drop_index("ix_source_events_unprocessed", table_name="source_events", schema="inbox")
    op.drop_table("source_events", schema="inbox")
