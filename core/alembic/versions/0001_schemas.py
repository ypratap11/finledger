"""schemas

Revision ID: 0001
Revises:
Create Date: 2026-04-14
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS inbox")
    op.execute("CREATE SCHEMA IF NOT EXISTS ledger")
    op.execute("CREATE SCHEMA IF NOT EXISTS revrec")
    op.execute("CREATE SCHEMA IF NOT EXISTS gl")
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")
    op.execute("CREATE SCHEMA IF NOT EXISTS recon")


def downgrade() -> None:
    for s in ["recon", "audit", "gl", "revrec", "ledger", "inbox"]:
        op.execute(f"DROP SCHEMA IF EXISTS {s} CASCADE")
