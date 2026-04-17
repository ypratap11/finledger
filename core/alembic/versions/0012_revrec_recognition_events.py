"""revrec recognition_events

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recognition_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("revrec.recognition_runs.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("obligation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("revrec.performance_obligations.id"), nullable=False),
        sa.Column("recognized_cents", sa.BigInteger, nullable=False),
        sa.Column("recognized_through", sa.Date, nullable=False),
        schema="revrec",
    )
    op.create_index("ix_recognition_events_obligation", "recognition_events",
                    ["obligation_id"], schema="revrec")
    op.create_index("ix_recognition_events_run", "recognition_events",
                    ["run_id"], schema="revrec")


def downgrade() -> None:
    op.drop_index("ix_recognition_events_run", table_name="recognition_events", schema="revrec")
    op.drop_index("ix_recognition_events_obligation", table_name="recognition_events", schema="revrec")
    op.drop_table("recognition_events", schema="revrec")
