"""revrec recognition_runs

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recognition_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_through_date", sa.Date, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("obligations_processed", sa.Integer, nullable=False,
                  server_default=sa.text("0")),
        sa.Column("total_recognized_cents", sa.BigInteger, nullable=False,
                  server_default=sa.text("0")),
        sa.Column("journal_entry_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ledger.journal_entries.id"), nullable=True),
        schema="revrec",
    )


def downgrade() -> None:
    op.drop_table("recognition_runs", schema="revrec")
