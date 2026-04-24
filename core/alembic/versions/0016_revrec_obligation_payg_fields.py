"""revrec: PAYG fields on performance_obligations

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "performance_obligations",
        sa.Column("price_per_unit_cents", sa.Integer, nullable=True),
        schema="revrec",
    )
    op.add_column(
        "performance_obligations",
        sa.Column(
            "unbilled_ar_account_code", sa.Text,
            nullable=False, server_default="1500-UNBILLED-AR",
        ),
        schema="revrec",
    )
    op.drop_constraint("ck_perf_obligations_pattern", "performance_obligations", schema="revrec")
    op.create_check_constraint(
        "ck_perf_obligations_pattern",
        "performance_obligations",
        "pattern IN ('ratable_daily', 'point_in_time', 'consumption', 'consumption_payg')",
        schema="revrec",
    )
    op.create_check_constraint(
        "ck_perf_obligations_payg_price",
        "performance_obligations",
        "pattern <> 'consumption_payg' OR (price_per_unit_cents IS NOT NULL AND price_per_unit_cents > 0)",
        schema="revrec",
    )
    # Relax consumption-units to apply only to prepaid 'consumption'
    op.drop_constraint("ck_perf_obligations_consumption_units", "performance_obligations", schema="revrec")
    op.create_check_constraint(
        "ck_perf_obligations_consumption_units",
        "performance_obligations",
        "pattern <> 'consumption' OR (units_total IS NOT NULL AND units_total > 0)",
        schema="revrec",
    )
    # Allow nullable total_amount_cents for PAYG; conditional CHECK enforces
    op.alter_column(
        "performance_obligations", "total_amount_cents",
        existing_type=sa.BigInteger(), nullable=True, schema="revrec",
    )
    op.create_check_constraint(
        "ck_perf_obligations_amount_required",
        "performance_obligations",
        "pattern = 'consumption_payg' OR total_amount_cents IS NOT NULL",
        schema="revrec",
    )
    # Extend period CHECK so PAYG also allowed without end_date
    op.drop_constraint("ck_perf_obligations_period", "performance_obligations", schema="revrec")
    op.create_check_constraint(
        "ck_perf_obligations_period",
        "performance_obligations",
        "pattern IN ('point_in_time', 'consumption', 'consumption_payg') OR "
        "(end_date IS NOT NULL AND end_date >= start_date)",
        schema="revrec",
    )


def downgrade() -> None:
    op.drop_constraint("ck_perf_obligations_period", "performance_obligations", schema="revrec")
    op.create_check_constraint(
        "ck_perf_obligations_period",
        "performance_obligations",
        "pattern IN ('point_in_time', 'consumption') OR "
        "(end_date IS NOT NULL AND end_date >= start_date)",
        schema="revrec",
    )
    op.drop_constraint("ck_perf_obligations_amount_required", "performance_obligations", schema="revrec")
    op.alter_column(
        "performance_obligations", "total_amount_cents",
        existing_type=sa.BigInteger(), nullable=False, schema="revrec",
    )
    op.drop_constraint("ck_perf_obligations_consumption_units", "performance_obligations", schema="revrec")
    op.create_check_constraint(
        "ck_perf_obligations_consumption_units",
        "performance_obligations",
        "pattern <> 'consumption' OR units_total IS NOT NULL",
        schema="revrec",
    )
    op.drop_constraint("ck_perf_obligations_payg_price", "performance_obligations", schema="revrec")
    op.drop_constraint("ck_perf_obligations_pattern", "performance_obligations", schema="revrec")
    op.create_check_constraint(
        "ck_perf_obligations_pattern",
        "performance_obligations",
        "pattern IN ('ratable_daily', 'point_in_time', 'consumption')",
        schema="revrec",
    )
    op.drop_column("performance_obligations", "unbilled_ar_account_code", schema="revrec")
    op.drop_column("performance_obligations", "price_per_unit_cents", schema="revrec")
