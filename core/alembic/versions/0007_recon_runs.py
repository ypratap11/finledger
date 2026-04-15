"""recon.recon_runs

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recon_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recon_type", sa.Text, nullable=False),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("matched_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("unmatched_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("mismatched_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        schema="recon",
    )
    op.create_table(
        "recon_breaks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("recon.recon_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("external_ref", sa.Text, nullable=True),
        sa.Column("external_amount_cents", sa.BigInteger, nullable=True),
        sa.Column("ledger_amount_cents", sa.BigInteger, nullable=True),
        sa.Column("details", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="recon",
    )
    op.create_index("ix_recon_breaks_run", "recon_breaks", ["run_id"], schema="recon")


def downgrade() -> None:
    op.drop_index("ix_recon_breaks_run", table_name="recon_breaks", schema="recon")
    op.drop_table("recon_breaks", schema="recon")
    op.drop_table("recon_runs", schema="recon")
