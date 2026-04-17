"""revrec index naming + recognition_runs.journal_entry_id index

Revision ID: 0013
Revises: 0012

Cleanup from Batch A code review:
- Rename ix_perf_obligations_contract -> ix_performance_obligations_contract
  (M1 convention uses the full table name: ix_journal_lines_entry,
  ix_recon_breaks_run, ix_source_events_unprocessed).
- Add ix_recognition_runs_journal_entry for the recognition-to-journal
  lookup path used by the runs timeline UI.
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER INDEX revrec.ix_perf_obligations_contract "
        "RENAME TO ix_performance_obligations_contract"
    )
    op.create_index(
        "ix_recognition_runs_journal_entry",
        "recognition_runs",
        ["journal_entry_id"],
        schema="revrec",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recognition_runs_journal_entry",
        table_name="recognition_runs",
        schema="revrec",
    )
    op.execute(
        "ALTER INDEX revrec.ix_performance_obligations_contract "
        "RENAME TO ix_perf_obligations_contract"
    )
