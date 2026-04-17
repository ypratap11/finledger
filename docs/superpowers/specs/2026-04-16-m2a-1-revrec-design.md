# M2a-1: ASC 606 Revenue Recognition — Core Engine

**Date:** 2026-04-16
**Status:** Approved
**Scope:** First of three sub-milestones toward full ASC 606. Covers Step 5 (recognition) and the Step 1/2 data model needed to feed it. M2a-2 adds SSP allocation + contract modifications. M2a-3 adds variable consideration + constraint.

## Motivation

FinLedger M1 proves the ledger + ingest + recon spine. The next foundational capability is revenue recognition under ASC 606. Every SaaS finance team needs this; most either hack it into spreadsheets or pay Zuora RevPro / Sage Intacct to do it. Building it into FinLedger is the clearest value differentiator vs. plain ledgers (Formance, Modern Treasury) which punt this problem.

M2a-1 is scoped to the recognition *engine* and its surrounding data model — the part that actually posts deferred-to-recognized journal entries over time. It does not attempt the hard allocation math (SSP) or variable-consideration constraint logic — those come in M2a-2 and M2a-3 respectively.

## Non-Goals

- **SSP allocation** (M2a-2). Obligations in M2a-1 have their full amount pre-set; we don't allocate transaction price across bundled obligations.
- **Contract modifications / amendments** (M2a-2). Obligations are immutable once created. Cancellation is a status flip with no retroactive effect.
- **Variable consideration + constraint** (M2a-3). All amounts are fixed at obligation creation.
- **Consumption-based recognition** (M2a-1.5). No usage-events pipeline in this milestone.
- **Milestone-based recognition**. Rare; skip until requested.
- **Multi-currency** — M1 assumption (`currency = USD`) carries forward.

## Architecture

Three concerns, cleanly separated:

1. **Obligation genesis** — how contracts and performance obligations enter the system.
2. **Recognition engine** — given obligations + a target date, compute and post the recognition journal entry.
3. **Read views** — waterfall + contract detail for the admin UI.

### Data Model

New schema `revrec` with four tables.

```sql
-- Contract: a customer commitment, typically 1:1 with a Zuora invoice
CREATE TABLE revrec.contracts (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  external_ref             TEXT NOT NULL UNIQUE,    -- e.g. Zuora invoice number "I-1001"
  customer_id              TEXT,                    -- free-form; from invoice payload
  effective_date           DATE NOT NULL,
  status                   TEXT NOT NULL DEFAULT 'active'
                           CHECK (status IN ('active', 'cancelled')),
  total_amount_cents       BIGINT NOT NULL,
  currency                 TEXT NOT NULL DEFAULT 'USD',
  created_from_event_id    UUID REFERENCES inbox.source_events(id),
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Performance obligation: a distinct promise with its own recognition pattern
CREATE TABLE revrec.performance_obligations (
  id                            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_id                   UUID NOT NULL REFERENCES revrec.contracts(id) ON DELETE RESTRICT,
  description                   TEXT NOT NULL,
  pattern                       TEXT NOT NULL
                                CHECK (pattern IN ('ratable_daily', 'point_in_time')),
  start_date                    DATE NOT NULL,
  end_date                      DATE,                -- NULL for point_in_time
  total_amount_cents            BIGINT NOT NULL CHECK (total_amount_cents > 0),
  currency                      TEXT NOT NULL DEFAULT 'USD',
  deferred_revenue_account_code TEXT NOT NULL DEFAULT '2000-DEFERRED-REV',
  revenue_account_code          TEXT NOT NULL DEFAULT '4000-REV-SUB',
  created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (pattern = 'point_in_time' OR (end_date IS NOT NULL AND end_date >= start_date))
);
CREATE INDEX ix_perf_obligations_contract ON revrec.performance_obligations(contract_id);

-- Recognition run: one per daily execution (or on-demand trigger)
CREATE TABLE revrec.recognition_runs (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_through_date         DATE NOT NULL,           -- recognize all activity up to this date inclusive
  started_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at              TIMESTAMPTZ,
  obligations_processed    INTEGER NOT NULL DEFAULT 0,
  total_recognized_cents   BIGINT NOT NULL DEFAULT 0,
  journal_entry_id         UUID REFERENCES ledger.journal_entries(id)
);

-- Recognition event: audit trail linking runs to obligation amounts
CREATE TABLE revrec.recognition_events (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id                   UUID NOT NULL REFERENCES revrec.recognition_runs(id) ON DELETE CASCADE,
  obligation_id            UUID NOT NULL REFERENCES revrec.performance_obligations(id),
  recognized_cents         BIGINT NOT NULL,
  recognized_through       DATE NOT NULL            -- high-water mark after this event
);
CREATE INDEX ix_recognition_events_obligation ON revrec.recognition_events(obligation_id);
CREATE INDEX ix_recognition_events_run ON revrec.recognition_events(run_id);
```

Invariant: for any obligation, `SUM(recognized_cents)` across all its `recognition_events` ≤ `total_amount_cents`. Enforced by the engine (not a DB constraint, since the constraint would need a subquery).

### Obligation Genesis

Two entry paths:

**Path B — Convention-based (from Zuora webhooks).**
The existing `map_invoice_posted` mapper in `core/src/finledger/posting/zuora_invoice.py` posts DR AR / CR Deferred Revenue (unchanged). After the posting succeeds, the posting engine calls a new `revrec.genesis.from_zuora_invoice(payload, source_event_id)` helper that:

1. Reads `metadata.service_period_start` and `metadata.service_period_end` from the invoice payload (new fields; tolerated as absent).
2. If both are present, creates a `contracts` row (external_ref = invoice number) and one `performance_obligations` row with `pattern='ratable_daily'`, the period dates, and the full invoice amount.
3. If absent, logs and skips — the invoice still posts, just no obligation is auto-created.

**Path A — Admin API (fallback / manual).**
For one-time fees, back-dated corrections, and demo seeding. Two endpoints:

- `POST /revrec/contracts` — body: `{external_ref, customer_id, effective_date, total_amount_cents, currency}` → returns contract id. Idempotent on `external_ref`.
- `POST /revrec/contracts/{id}/obligations` — body: `{description, pattern, start_date, end_date, total_amount_cents, deferred_revenue_account_code?, revenue_account_code?}` → returns obligation id.

The convention case (B) simply calls these helpers internally.

### Recognition Engine

Core function:

```python
def compute_recognition(
    obligation: PerformanceObligation,
    already_recognized_cents: int,
    already_recognized_through: date | None,
    run_through_date: date,
) -> RecognitionDelta | None:
    """Returns the amount to recognize between already_recognized_through and
    run_through_date (inclusive), or None if there's nothing to recognize."""
```

Pattern semantics:

**`ratable_daily`:**
- `days_in_period = (end_date - start_date).days + 1` (inclusive of both endpoints).
- `daily_cents = total_amount_cents // days_in_period`, with any rounding remainder absorbed on `end_date`.
- On run for date `D`, let `from_day = max((already_through or start_date - 1) + 1 day, start_date)`:
  - If `D < start_date`: no recognition.
  - If `start_date ≤ D ≤ end_date`: recognize `daily_cents * ((D - from_day).days + 1)`.
  - If `D > end_date`: recognize `total_amount_cents - already_recognized_cents` (absorbs rounding remainder on the final posting).
- Result: total recognized after `end_date` exactly equals `total_amount_cents`, regardless of rounding path or whether the run happened daily or all at once at the end.

**`point_in_time`:**
- If `D ≥ start_date` and nothing yet recognized: recognize the full `total_amount_cents`.
- Else: no recognition.

### Posting

One journal entry per run. The engine:

1. Loads all active obligations with `start_date ≤ run_through_date` and not yet fully recognized.
2. Computes `RecognitionDelta` for each.
3. Groups deltas by `(deferred_revenue_account_code, 'debit')` and `(revenue_account_code, 'credit')`, summing amounts. For M2a-1 with one deferred + one revenue account, this collapses to two lines.
4. Calls the existing `post_entry` helper with a memo like `"revrec:daily:2026-04-16"` and those aggregated lines.
5. Inserts one `recognition_events` row per obligation (preserving per-obligation audit trail even though the JE is aggregated).
6. Updates `recognition_runs.journal_entry_id`, `obligations_processed`, `total_recognized_cents`, `finished_at`.

Idempotency: a run with `run_through_date = D` is a no-op if a completed run for `D` (or a later date) already exists. This matches the "idempotent catch-up" semantics of M1's posting engine.

### Scheduler

Uses the existing `apscheduler` dependency. Registered in `core/src/finledger/workers/revrec_scheduler.py` as a daily job at 01:00 UTC that calls `run_recognition(through_date=yesterday)`. The scheduler itself is optional — a separate process (`python -m finledger.workers.revrec_scheduler`) that finance teams can disable if they prefer pure-on-demand runs.

### APIs (FastAPI)

Added under `core/src/finledger/ui/routes/revrec.py`:

```
POST   /revrec/contracts                         # create contract (Path A)
GET    /revrec/contracts                         # list, paginated
GET    /revrec/contracts/{id}                    # detail with obligations + recognition state
POST   /revrec/contracts/{id}/obligations        # add obligation (Path A)
POST   /revrec/run                               # on-demand trigger; body: {through_date}
GET    /revrec/runs                              # list runs, descending
GET    /revrec/waterfall?months=12               # JSON payload for waterfall chart
```

All read endpoints return HTMX-friendly HTML by default, JSON via `Accept: application/json`.

### Rev Waterfall View

At `/revrec`. Server-rendered table with columns = next N months (default 12) + a final "Beyond" column. Rows:

- **TOTAL** (always shown, pinned at top).
- **Stratified summary bucket rows** (backward-compatible with ASC 606 disclosures):
  - "Next 3 months"
  - "4–12 months"
  - "12+ months"
- **Per-contract detail** (hidden by default behind a "show detail" toggle).

Computation: for each obligation with remaining unrecognized amount, project daily recognition forward and sum by month. Point-in-time obligations put their full amount in their `start_date`'s month. Cancelled contracts excluded.

Horizon cap: 36 months forward. Anything past 36 months is aggregated into "Beyond."

## UI Design Direction

The revrec pages adopt a distinct **"Editorial Finance"** aesthetic — the gravitas of an annual report meets the density of a financial terminal. This is justified by audience and content: CFOs, controllers, and auditors spend focused time here reading long tables of future revenue, and the visual register should match the seriousness of the numbers. The existing M1 pages (Flow, Inbox, Journal, Recon) keep their current utilitarian look; revrec is a deliberately more considered section, accessed via a new **"Revenue"** nav entry between "Journal" and "Reconciliation."

### Design pillars

- **Type system upgrade.** Introduce **Fraunces** (variable serif, via Google Fonts, with the `opsz` optical-size axis) for headlines and hero money figures. Keep **Inter** for body and nav (continuity with M1). Keep **JetBrains Mono** for tabular numeric data, with `font-feature-settings: "tnum" 1` so digits align under each other in right-aligned columns.
- **Surface hierarchy.** Add a warm bone/cream surface (`#faf8f3`) for hero panels and contract cards, sitting on the existing cool slate backdrop. The bone is "paper" — the serious numbers live there. A barely-perceptible SVG-noise grain adds warmth without visual noise.
- **Color of money.** Two restrained accents: `#1a4d3a` (deep forest) for recognized revenue, `#c2410c` (burnt amber) for deferred / unrecognized future. Red reserved for breaks only. The M1 brand indigo is de-emphasized in these pages.
- **Rules over borders.** Hairline rules (`0.5px solid rgba(15,23,42,0.12)`) replace card borders wherever possible — horizontal between sections, vertical between waterfall columns. Evokes a letterpress / editorial feel.
- **Display numbers.** Hero money figures (KPI panel, waterfall TOTAL) in Fraunces at 48–64px with `font-variation-settings: "wght" 500, "opsz" 48`. Small-caps labels above them via `font-feature-settings: "smcp"`.
- **Fleuron dividers** (`❦` or `§`) between major sections — typographic furniture that signals "this is a document, not a dashboard."
- **Motion, restrained.** Number roll-up on load over 400ms with `cubic-bezier(0.16, 1, 0.3, 1)`. Waterfall rows fade in with a 30ms stagger. Cream-tint row highlight on hover. No shimmer, parallax, or ornamental animation.

### Design tokens (additions to `base.html :root`)

```css
--paper: #faf8f3;
--ink-serif: #1c1917;
--rule: rgba(15, 23, 42, 0.12);
--rule-strong: rgba(15, 23, 42, 0.25);
--money-recognized: #1a4d3a;
--money-deferred: #c2410c;
--money-neutral: #78716c;
--display: 'Fraunces', 'Times New Roman', Georgia, serif;
```

### Per-page treatment

**`/revrec` — Waterfall (hero page):**
- Top strip on bone surface: three pillar KPIs — *ARR*, *Deferred revenue balance*, *Recognized MTD*. Each is a 56px Fraunces number with a small-caps label and a one-line sparkline beneath in the money color. Borderless, separated by vertical hairline rules.
- Fleuron divider.
- Stratified summary strip: *Next 3 months · Months 4–12 · Beyond*, each as number + thin horizontal progress bar showing its share of total backlog.
- Waterfall table: full-bleed, generous column widths. Contract name column in Fraunces italic. Numbers right-aligned in JetBrains Mono with tabular figures. Per-column hairline rules. Row hover fills whole row with `--paper`. Zero cells rendered as `—` in `--money-neutral` to reduce visual noise.
- Pinned footer TOTAL row in Fraunces at 20px with a top double-rule (`border-top: 3px double var(--rule-strong)`).

**`/revrec/contracts/{id}` — Contract detail:**
- Masthead: Fraunces 48px contract `external_ref` as headline. Small-caps subtitle: status · pattern summary · term · customer · total amount.
- Obligation cards stacked on bone surface, one per performance obligation:
  - Obligation description in serif at 18px.
  - Horizontal stacked progress bar: recognized portion in `--money-recognized`, deferred in `--money-deferred`, a thin tick mark at "today's" position.
  - Pattern + date range in small-caps mono.
  - Collapsed recent-events mini-table (last 5 recognitions) with "view all" link.
- Hairline rules between obligations, no outer card border.

**`/revrec/runs` — Audit trail:**
- Chronological timeline, most recent first. Each run rendered as a dateline-style entry: serif date, monospace amounts, one-line memo linking to the posted JE. Looks like a ship's log, not a database dump.

**`/revrec/contracts` — Contract list:**
- Editorial table: contracts as rows (customer, term, status, total). Serif `external_ref`, mono amounts. Same hairline-rule treatment as the waterfall. Hover reveals a small `→` glyph on the right to signal drill-down.

### What this is NOT

- Not a redesign of existing M1 pages. Nav, Flow, Inbox, Journal, and Recon keep their current utilitarian look. Revrec is scoped as a distinct editorial section because it is the long-form analytical surface.
- Not a chart library. All visualizations (progress bars, sparklines, timelines) are hand-built CSS/SVG, ~20 lines each. No Chart.js, no D3.
- Not a dark mode. Bone on slate is the identity; dark mode is a later concern.

## Data Flow

```
Zuora invoice.posted webhook
      │
      ▼
insert_source_event ──► inbox.source_events
      │
      ▼
run_once (posting engine)
      │
      ├──► map_invoice_posted ──► post_entry (DR AR / CR Deferred Rev)
      │
      └──► revrec.genesis.from_zuora_invoice
                │
                ▼
            (if service period metadata present)
                │
                ▼
            revrec.contracts + revrec.performance_obligations

---- Daily, separately (scheduler or on-demand) ----

run_recognition(through_date)
      │
      ├──► load active obligations
      ├──► compute RecognitionDelta per obligation
      ├──► aggregate lines by (account, side)
      ├──► post_entry (DR Deferred Rev / CR Revenue, one JE)
      └──► insert revrec.recognition_events
```

## Error Handling

| Condition | Behavior |
|---|---|
| Obligation with `start_date > end_date` | Rejected at creation (CHECK constraint). |
| Obligation missing end_date for ratable | Rejected at creation (CHECK constraint). |
| `total_amount_cents <= 0` | Rejected at creation (CHECK constraint). |
| Duplicate invoice creates duplicate contract | Prevented by `UNIQUE(external_ref)`; genesis helper catches this and logs at INFO. |
| Invoice without service period metadata | Skip obligation creation, log at DEBUG. Invoice still posts. |
| Recognition run for past date that was already run | No-op. `recognition_runs` is searched for any run with `run_through_date >= requested`. |
| `post_entry` fails (balance check, DB error) | Propagate; `recognition_runs.finished_at` stays NULL; `recognition_events` rolled back in same transaction. Retry is safe. |
| Obligation's revenue account code doesn't exist | Propagate `LookupError` from `get_account_id`; run fails; operator must seed account. |

## Testing Strategy

**Unit tests** (`tests/unit/test_revrec_compute.py`):
- Ratable: single-day obligation, multi-day, mid-period recognition, past end_date catch-up with rounding.
- Point-in-time: before start, on start, after start already recognized.
- Rounding: `$100 / 7 days` recognizes exactly $100 by end of period.
- Negative case: obligation fully recognized returns `None`.

**Integration tests** (`tests/integration/test_revrec_engine.py`):
- Seed contract + 3 obligations, run for various through-dates, assert journal entries posted + `recognition_events` rows correct.
- Idempotent: same `through_date` twice produces one JE, not two.
- Zuora genesis: webhook with service period metadata creates contract+obligation; without metadata only posts the original invoice JE.
- Waterfall: seed known obligations, hit `/revrec/waterfall`, assert month columns sum correctly.

**Property-based test** (`tests/property/test_revrec_invariants.py`):
For any randomized set of contracts/obligations, running recognition through `end_date` of the last obligation:
- Total recognized revenue across all obligations equals `SUM(total_amount_cents)` of non-cancelled obligations.
- Total deferred revenue account balance goes to zero.
- Trial balance remains zero (reuses existing invariant from M1).

## Migration Plan

Four new migrations (0009–0012):

- `0009_revrec_schema_and_contracts.py` — schema + contracts table.
- `0010_revrec_performance_obligations.py` — obligations + indexes.
- `0011_revrec_recognition_runs.py` — runs table + FK to journal_entries.
- `0012_revrec_recognition_events.py` — events table + indexes.

All independent of each other (no downstream M1 changes). Rollback = drop in reverse order.

## UI Changes

Additions to `core/src/finledger/ui/`:
- New route: `core/src/finledger/ui/routes/revrec.py`.
- New templates: `revrec_waterfall.html`, `revrec_contract_list.html`, `revrec_contract_detail.html`, `revrec_runs.html`.
- New nav entry "Revenue" added to `base.html` between "Journal" and "Reconciliation".

## File Layout

```
core/src/finledger/
  revrec/
    __init__.py
    compute.py             # compute_recognition() — pure, heavily unit-tested
    engine.py              # run_recognition() — the orchestrator
    genesis.py             # from_zuora_invoice() — path B
    api.py                 # admin POST endpoints — path A
  models/
    revrec.py              # SQLAlchemy models
  ui/routes/
    revrec.py              # GET routes + waterfall
  ui/templates/
    revrec_waterfall.html
    revrec_contract_list.html
    revrec_contract_detail.html
    revrec_runs.html
  workers/
    __init__.py
    revrec_scheduler.py    # APScheduler daily job
core/alembic/versions/
  0009_revrec_schema_and_contracts.py
  0010_revrec_performance_obligations.py
  0011_revrec_recognition_runs.py
  0012_revrec_recognition_events.py
core/tests/
  unit/test_revrec_compute.py
  integration/test_revrec_engine.py
  property/test_revrec_invariants.py
```

## Scope Impact

Estimated 3–4 weeks of focused work. ~1,800 LOC + 4 migrations + ~25 tests. Does not modify any existing M1 code paths — layers cleanly on top.

## Future Milestones (Out of Scope)

- **M2a-1.5: Consumption-based recognition.** Adds `usage_events` table + a consumption pattern; obligations track `units_total` and `unit_price`.
- **M2a-2: Step 4 (SSP allocation) + contract modifications.** Multi-obligation contracts, bundled pricing with SSP-proportional allocation, amendments (prospective + cumulative catch-up).
- **M2a-3: Step 3 (variable consideration + constraint).** Expected-value and most-likely-amount methods, constraint test, true-up postings when estimates change.
- **M2b: Zuora sandbox deepening.** Real Zuora API, full webhook catalog, Zuora↔Ledger recon via recognized revenue amounts.
- **M2c: First real ERP connector.** Implements `JournalExporter` protocol (M1 Task 25b seam) for Oracle FBDI, NetSuite SuiteTalk, or SAP S/4HANA OData.
