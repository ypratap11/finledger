"""revrec performance_obligations

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "performance_obligations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("revrec.contracts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("pattern", sa.Text, nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("total_amount_cents", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'USD'")),
        sa.Column("deferred_revenue_account_code", sa.Text, nullable=False,
                  server_default=sa.text("'2000-DEFERRED-REV'")),
        sa.Column("revenue_account_code", sa.Text, nullable=False,
                  server_default=sa.text("'4000-REV-SUB'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("pattern IN ('ratable_daily', 'point_in_time')",
                           name="ck_perf_obligations_pattern"),
        sa.CheckConstraint("total_amount_cents > 0",
                           name="ck_perf_obligations_amount_positive"),
        sa.CheckConstraint(
            "pattern = 'point_in_time' OR (end_date IS NOT NULL AND end_date >= start_date)",
            name="ck_perf_obligations_period",
        ),
        schema="revrec",
    )
    op.create_index("ix_perf_obligations_contract", "performance_obligations",
                    ["contract_id"], schema="revrec")


def downgrade() -> None:
    op.drop_index("ix_perf_obligations_contract",
                  table_name="performance_obligations", schema="revrec")
    op.drop_table("performance_obligations", schema="revrec")
