# GL Journal Export — Design Spec

**Date:** 2026-04-15
**Status:** Approved
**Scope:** M1 addition — single new task (Task 25b)

## Motivation

FinLedger M1 ingests events from Stripe/Zuora, posts double-entry journal entries, and reconciles. The natural next step for any SaaS adopter is feeding these journal entries into their system-of-record GL — typically SAP S/4HANA, Oracle Fusion Cloud ERP, or NetSuite.

Building a native connector to any of those ERPs is a multi-week effort per ERP (FBDI, BAPI, IDoc, OAuth, middleware) and belongs in a later milestone. However, M1 must not close off that path: the ledger posting engine should have a clean seam for pluggable exporters so future ERP connectors land as drop-in implementations rather than refactors.

This spec covers two things:

1. A `JournalExporter` protocol that future ERP connectors will conform to.
2. A first concrete implementation: CSV export, which gives M1 a working end-to-end ingest-to-GL story and is usable in practice via the generic CSV-import tools that every ERP ships.

## Non-Goals

- ERP-specific output formats (Oracle FBDI, SAP IDoc/BAPI, NetSuite SuiteTalk). These are M2+.
- Period-close workflow (locking a closed period against further posting). Exports in M1 are ad-hoc by date range.
- Re-export protection on journal entries. Added when the first real ERP connector lands and round-trip status matters.
- Multi-dimension chart-of-accounts mapping (cost center, profit center, project). Single account axis only.
- Reverse reconciliation (comparing what the ERP posted back against what we exported).

## Architecture

### Exporter Protocol

```python
# core/src/finledger/export/base.py
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

@dataclass(frozen=True)
class DateRange:
    start: date   # inclusive
    end: date     # inclusive

@dataclass(frozen=True)
class ExportResult:
    exporter: str         # exporter.name
    period: DateRange
    entries_exported: int
    file_path: Path
    checksum: str         # sha256 hex of file contents
    run_id: int           # gl.export_runs.id

class JournalExporter(Protocol):
    name: str
    def export(self, period: DateRange, out_dir: Path) -> ExportResult: ...
```

Each implementation (CSV now; SAP, Oracle, NetSuite later) is a single module in `core/src/finledger/export/` conforming to this protocol.

### CSV Exporter

**Aggregation.** Reads `ledger.journal_entries` and `ledger.journal_lines` for entries whose `posting_date` falls within `[period.start, period.end]`. Groups lines by `(posting_date, account_code, currency)` and emits one summarized row per group:

```
posting_date, account_code, account_name, debit, credit, currency, entry_count, source_refs
```

- `debit` and `credit`: summed amounts (one is always zero per row — a group is either net-debit or net-credit after summing)
- `entry_count`: number of individual journal lines collapsed into the row
- `source_refs`: comma-joined list of `inbox.source_events.external_id` values backing the group (resolved via `journal_entries.source_event_id` → `inbox.source_events.id`). Truncated to 1024 chars if it overflows, with `...` suffix.

**Amounts are stored and exported as integer minor units** (cents, paise, etc.) — no floating point, consistent with the ledger's existing representation.

**Invariant:** For any period, `SUM(debit) - SUM(credit) = 0` across all rows. Enforced as an assertion before file write; violation raises `ExportIntegrityError`.

**Output.** `{out_dir}/journal_{start}_{end}_{exporter}.csv` (e.g. `journal_2026-04-01_2026-04-30_csv.csv`). UTF-8, RFC 4180 quoting, header row included.

**Audit.** Each run writes a row to a new table:

```sql
CREATE TABLE gl.export_runs (
  id            BIGSERIAL PRIMARY KEY,
  exporter      TEXT        NOT NULL,
  period_start  DATE        NOT NULL,
  period_end    DATE        NOT NULL,
  file_path     TEXT        NOT NULL,
  checksum      TEXT        NOT NULL,   -- sha256 hex
  entries_count INTEGER     NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### CLI

```
finledger export-journal --from 2026-04-01 --to 2026-04-30 [--out ./exports] [--exporter csv]
```

- `--exporter` defaults to `csv`. Future connectors register their `name` here.
- Exits non-zero on `ExportIntegrityError` or DB errors.
- Prints `run_id`, `file_path`, `checksum`, `entries_count` to stdout on success.

## Data Flow

```
ledger.journal_lines ──┐
                       ├──► aggregator (group by date+account+currency)
ledger.journal_entries ┘             │
                                     ▼
                               sanity check (debits = credits)
                                     │
                                     ▼
                               write CSV → compute sha256
                                     │
                                     ▼
                               INSERT gl.export_runs row
                                     │
                                     ▼
                               return ExportResult
```

## Error Handling

| Condition | Behavior |
|---|---|
| Empty period (no entries) | Write header-only CSV, record export_runs row with `entries_count=0`, exit 0 |
| Debits ≠ credits in aggregate | Raise `ExportIntegrityError`, do not write file, do not insert export_runs row |
| DB connection failure mid-run | Propagate. If it fails before the file is written, nothing has happened. If it fails after the file is written but before the `export_runs` row is inserted, delete the file and re-raise. |
| Disk write failure | Propagate; no `export_runs` row inserted. |

Concurrent exports of the same period are serialized via a PostgreSQL advisory lock keyed on `hashtext(period_start||period_end||exporter)`.

## Testing

**Unit tests** (`tests/unit/test_export_csv.py`):
- Aggregation: 3 journal entries with overlapping accounts → verify group sums
- Empty period → header-only file, zero count
- Debit/credit imbalance (fabricated) → raises `ExportIntegrityError`
- CSV format: RFC 4180 quoting of account names with commas/quotes
- `source_refs` truncation at 1024 chars

**Integration tests** (`tests/integration/test_export_csv_end_to_end.py`):
- Seed ledger via `post_entry` helper with known Stripe events
- Run CSV exporter over period
- Parse CSV back, assert: row count, per-account totals match `SELECT` against `journal_lines`, file checksum matches `gl.export_runs.checksum`
- Run exporter twice concurrently (two threads) → advisory lock serializes, both succeed with distinct `run_id`s and identical output

## Migration

New migration `core/alembic/versions/0007_gl_export_runs.py` (following 0001 schemas, 0002 inbox, 0003 accounts, 0004 journals, 0005 triggers, 0006 recon). Adds `gl.export_runs` table only.

## File Layout

```
core/src/finledger/export/
  __init__.py
  base.py          # Protocol + dataclasses + ExportIntegrityError
  csv_exporter.py  # CsvJournalExporter
  cli.py           # argparse entry point for `finledger export-journal`

core/tests/unit/test_export_csv.py
core/tests/integration/test_export_csv_end_to_end.py
core/alembic/versions/NNNN_gl_export_runs.py
```

Registered in `pyproject.toml` as a console script:

```toml
[project.scripts]
finledger = "finledger.cli:main"
```

A small dispatcher in `finledger/cli.py` routes `export-journal` to `export.cli.main`, leaving room for future subcommands (`verify-chain`, etc.) without further packaging changes.

## Scope Impact on M1 Plan

Insert as **Task 25b** between Task 25 (admin dashboard) and Task 26 (property-based tests). Does not modify any existing task. Estimated ~1 day of work: ~150 LOC + 1 migration + ~8 tests.

## Future Milestones (Out of Scope)

- **M2: SAP connector** — `SapFbdiExporter` writing SAP-compatible IDoc or FBDI-equivalent CSV; OAuth to S/4HANA Cloud; middleware-compatible file drop for on-prem ECC.
- **M2: Oracle connector** — `OracleFbdiExporter` writing FBDI CSV, uploading via UCM REST, triggering the ERP Integration Service import job.
- **M3: Period close + re-export protection** — lock closed periods, mark entries `exported_at`, block re-export of already-exported entries without an explicit `--reexport` flag, track round-trip status (posted/rejected per ERP).
- **M3: Dimension mapping** — cost center, profit center, project; customer-supplied account mapping table.
