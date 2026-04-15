"""ledger.accounts

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("normal_side", sa.Text, nullable=False),
        sa.CheckConstraint(
            "type IN ('asset','liability','equity','revenue','expense')",
            name="ck_accounts_type",
        ),
        sa.CheckConstraint("normal_side IN ('debit','credit')", name="ck_accounts_normal_side"),
        schema="ledger",
    )


def downgrade() -> None:
    op.drop_table("accounts", schema="ledger")
