"""ledger journal

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "journal_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("inbox.source_events.id"), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'posted'")),
        sa.Column("preparer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approver_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reverses", postgresql.UUID(as_uuid=True), sa.ForeignKey("ledger.journal_entries.id"), nullable=True),
        sa.Column("memo", sa.Text, nullable=True),
        sa.CheckConstraint(
            "status IN ('draft','pending_approval','posted','reversed')",
            name="ck_journal_entries_status",
        ),
        sa.UniqueConstraint("source_event_id", name="uq_journal_source_event"),
        schema="ledger",
    )
    op.create_table(
        "journal_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ledger.journal_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("ledger.accounts.id"), nullable=False),
        sa.Column("side", sa.Text, nullable=False),
        sa.Column("amount_cents", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'USD'")),
        sa.Column("external_ref", sa.Text, nullable=True),
        sa.Column("dimension_json", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("side IN ('debit','credit')", name="ck_journal_lines_side"),
        sa.CheckConstraint("amount_cents > 0", name="ck_journal_lines_amount_positive"),
        schema="ledger",
    )
    op.create_index("ix_journal_lines_external_ref", "journal_lines", ["external_ref"], schema="ledger")
    op.create_index("ix_journal_lines_entry", "journal_lines", ["entry_id"], schema="ledger")


def downgrade() -> None:
    op.drop_index("ix_journal_lines_entry", table_name="journal_lines", schema="ledger")
    op.drop_index("ix_journal_lines_external_ref", table_name="journal_lines", schema="ledger")
    op.drop_table("journal_lines", schema="ledger")
    op.drop_table("journal_entries", schema="ledger")
