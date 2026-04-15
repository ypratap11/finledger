"""ledger balance + immutability triggers

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
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

    op.execute("""
    CREATE CONSTRAINT TRIGGER trg_entry_balanced
      AFTER INSERT OR UPDATE OR DELETE ON ledger.journal_lines
      DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW EXECUTE FUNCTION ledger.check_entry_balanced();
    """)

    op.execute("""
    CREATE OR REPLACE FUNCTION ledger.forbid_mutation_if_posted() RETURNS TRIGGER AS $$
    DECLARE
      parent_status text;
    BEGIN
      IF TG_TABLE_NAME = 'journal_entries' THEN
        IF OLD.status = 'posted' AND TG_OP = 'UPDATE' THEN
          IF NEW.status = 'reversed' THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'journal_entry % is posted and immutable', OLD.id;
        END IF;
        IF OLD.status = 'posted' AND TG_OP = 'DELETE' THEN
          RAISE EXCEPTION 'journal_entry % is posted and cannot be deleted', OLD.id;
        END IF;
      ELSE
        SELECT status INTO parent_status FROM ledger.journal_entries
          WHERE id = COALESCE(NEW.entry_id, OLD.entry_id);
        IF parent_status = 'posted' THEN
          RAISE EXCEPTION 'journal_lines for posted entry are immutable';
        END IF;
      END IF;
      RETURN COALESCE(NEW, OLD);
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute("""
    CREATE TRIGGER trg_entries_immutable
      BEFORE UPDATE OR DELETE ON ledger.journal_entries
      FOR EACH ROW EXECUTE FUNCTION ledger.forbid_mutation_if_posted();
    """)

    op.execute("""
    CREATE TRIGGER trg_lines_immutable
      BEFORE UPDATE OR DELETE ON ledger.journal_lines
      FOR EACH ROW EXECUTE FUNCTION ledger.forbid_mutation_if_posted();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_lines_immutable ON ledger.journal_lines")
    op.execute("DROP TRIGGER IF EXISTS trg_entries_immutable ON ledger.journal_entries")
    op.execute("DROP FUNCTION IF EXISTS ledger.forbid_mutation_if_posted()")
    op.execute("DROP TRIGGER IF EXISTS trg_entry_balanced ON ledger.journal_lines")
    op.execute("DROP FUNCTION IF EXISTS ledger.check_entry_balanced()")
