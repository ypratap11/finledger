"""revrec schema + contracts

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS revrec")
    op.create_table(
        "contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("external_ref", sa.Text, nullable=False, unique=True),
        sa.Column("customer_id", sa.Text, nullable=True),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'active'")),
        sa.Column("total_amount_cents", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'USD'")),
        sa.Column("created_from_event_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("inbox.source_events.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('active', 'cancelled')", name="ck_contracts_status"),
        sa.CheckConstraint("total_amount_cents > 0", name="ck_contracts_amount_positive"),
        schema="revrec",
    )


def downgrade() -> None:
    op.drop_table("contracts", schema="revrec")
    op.execute("DROP SCHEMA IF EXISTS revrec CASCADE")
