"""fix balance trigger: rename PL/pgSQL variable that shadowed the column

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION ledger.check_entry_balanced() RETURNS TRIGGER AS $$
    DECLARE
      total_debit bigint;
      total_credit bigint;
      v_entry_id uuid;
    BEGIN
      v_entry_id := COALESCE(NEW.entry_id, OLD.entry_id);
      SELECT
        COALESCE(SUM(CASE WHEN side = 'debit' THEN amount_cents ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN side = 'credit' THEN amount_cents ELSE 0 END), 0)
      INTO total_debit, total_credit
      FROM ledger.journal_lines
      WHERE journal_lines.entry_id = v_entry_id;

      IF total_debit <> total_credit THEN
        RAISE EXCEPTION 'journal entry % unbalanced: debit=% credit=%', v_entry_id, total_debit, total_credit;
      END IF;
      IF total_debit = 0 THEN
        RAISE EXCEPTION 'journal entry % has no lines', v_entry_id;
      END IF;
      RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION ledger.check_entry_balanced() RETURNS TRIGGER AS $$
    DECLARE
      total_debit bigint;
      total_credit bigint;
      entry_id uuid;
    BEGIN
      entry_id := COALESCE(NEW.entry_id, OLD.entry_id);
      SELECT
        COALESCE(SUM(CASE WHEN side = 'debit' THEN amount_cents ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN side = 'credit' THEN amount_cents ELSE 0 END), 0)
      INTO total_debit, total_credit
      FROM ledger.journal_lines
      WHERE journal_lines.entry_id = entry_id;

      IF total_debit <> total_credit THEN
        RAISE EXCEPTION 'journal entry % unbalanced: debit=% credit=%', entry_id, total_debit, total_credit;
      END IF;
      IF total_debit = 0 THEN
        RAISE EXCEPTION 'journal entry % has no lines', entry_id;
      END IF;
      RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    """)
