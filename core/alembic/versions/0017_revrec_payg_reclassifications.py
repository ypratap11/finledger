"""revrec: payg_reclassifications table

Revision ID: 0017
Revises: 0016
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payg_reclassifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("obligation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("amount_cents", sa.BigInteger, nullable=False),
        sa.Column("invoice_external_ref", sa.Text, nullable=True),
        sa.Column("billed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("journal_entry_id", UUID(as_uuid=True), nullable=False),
        sa.Column("source_event_id", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["obligation_id"], ["revrec.performance_obligations.id"]),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["ledger.journal_entries.id"]),
        sa.ForeignKeyConstraint(["source_event_id"], ["inbox.source_events.id"]),
        sa.CheckConstraint("amount_cents > 0", name="ck_payg_reclass_amount_positive"),
        schema="revrec",
    )
    op.create_index(
        "ix_payg_reclass_obligation",
        "payg_reclassifications",
        ["obligation_id"],
        schema="revrec",
    )


def downgrade() -> None:
    op.drop_index("ix_payg_reclass_obligation", table_name="payg_reclassifications", schema="revrec")
    op.drop_table("payg_reclassifications", schema="revrec")
