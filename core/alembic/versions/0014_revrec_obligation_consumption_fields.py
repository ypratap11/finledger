"""revrec obligation: units_total, unit_label, external_ref + CHECK updates

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "performance_obligations",
        sa.Column("units_total", sa.BigInteger, nullable=True),
        schema="revrec",
    )
    op.add_column(
        "performance_obligations",
        sa.Column("unit_label", sa.Text, nullable=True),
        schema="revrec",
    )
    op.add_column(
        "performance_obligations",
        sa.Column("external_ref", sa.Text, nullable=True),
        schema="revrec",
    )
    op.create_unique_constraint(
        "uq_performance_obligations_external_ref",
        "performance_obligations",
        ["external_ref"],
        schema="revrec",
    )
    op.drop_constraint(
        "ck_perf_obligations_pattern", "performance_obligations", schema="revrec"
    )
    op.create_check_constraint(
        "ck_perf_obligations_pattern",
        "performance_obligations",
        "pattern IN ('ratable_daily', 'point_in_time', 'consumption')",
        schema="revrec",
    )
    op.create_check_constraint(
        "ck_perf_obligations_consumption_units",
        "performance_obligations",
        "pattern <> 'consumption' OR units_total IS NOT NULL",
        schema="revrec",
    )
    op.drop_constraint(
        "ck_perf_obligations_period", "performance_obligations", schema="revrec"
    )
    op.create_check_constraint(
        "ck_perf_obligations_period",
        "performance_obligations",
        "pattern IN ('point_in_time', 'consumption') OR "
        "(end_date IS NOT NULL AND end_date >= start_date)",
        schema="revrec",
    )


def downgrade() -> None:
    op.drop_constraint("ck_perf_obligations_period", "performance_obligations", schema="revrec")
    op.create_check_constraint(
        "ck_perf_obligations_period",
        "performance_obligations",
        "pattern = 'point_in_time' OR (end_date IS NOT NULL AND end_date >= start_date)",
        schema="revrec",
    )
    op.drop_constraint("ck_perf_obligations_consumption_units", "performance_obligations", schema="revrec")
    op.drop_constraint("ck_perf_obligations_pattern", "performance_obligations", schema="revrec")
    op.create_check_constraint(
        "ck_perf_obligations_pattern",
        "performance_obligations",
        "pattern IN ('ratable_daily', 'point_in_time')",
        schema="revrec",
    )
    op.drop_constraint("uq_performance_obligations_external_ref", "performance_obligations", schema="revrec")
    op.drop_column("performance_obligations", "external_ref", schema="revrec")
    op.drop_column("performance_obligations", "unit_label", schema="revrec")
    op.drop_column("performance_obligations", "units_total", schema="revrec")
