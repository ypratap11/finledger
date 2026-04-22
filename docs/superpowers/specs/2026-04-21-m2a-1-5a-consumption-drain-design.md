# M2a-1.5a — Committed Usage Drain

**Date:** 2026-04-21
**Status:** Approved
**Scope:** First of three sub-milestones toward full consumption-based revenue recognition (M2a-1.5). Adds a `consumption` recognition pattern that drains a contract's deferred revenue proportional to units consumed, rather than by time elapsed.

## Motivation

M2a-1 covers time-based revenue recognition (ratable + point-in-time). The natural extension — and the next missing piece for any SaaS finance team running usage-based pricing — is a pattern that drains deferred revenue *as units are consumed*, not *as time passes*.

Real-world fit: Snowflake credits, Twilio platform fees, Datadog hosts, any API-priced product with a commitment. Customer prepays a $12k/year commitment → invoice posts `DR AR / CR Deferred Revenue` (same as subscription today) → as usage accrues, deferred revenue drains proportionally. If usage finishes early, deferred revenue hits zero; if it exceeds the commitment, recognition caps at the contract price (ASC 606 prohibits over-recognition) and excess units become an overage flag for M2a-1.5c.

M2a-1.5a is scoped to the *recognition* half. It does not bill overages, does not auto-invoice, and does not support pay-as-you-go (those are 1.5c, out-of-scope, and 1.5b respectively).

## Non-Goals

- **Pay-as-you-go** (no prior commitment, recognize on arrival). Deferred to M2a-1.5b.
- **Overage billing / invoicing**. Deferred to M2a-1.5c. M2a-1.5a stores the raw events so 1.5c can compute and flag overages without a data migration.
- **CSV batch import of usage**. When added later, it writes to the same `usage_events` table and reuses the same recognition path.
- **Real-time per-event recognition**. The existing daily recognition scheduler handles consumption — one JE per day per obligation (same cadence as ratable), not one JE per event.
- **Retroactive recognition to historical runs**. Events are recognized in the next daily run after receipt (`received_at`), not backdated to `occurred_at`. This preserves the M2a-1 invariant that completed runs are immutable.
- **Multi-tier pricing**. A consumption obligation has one unit price, derived from `total_amount_cents / units_total`. Tiered commitments (first 1M free, next 1M at X, etc.) are a later milestone.

## Architecture

Three additions layer on M2a-1 without disturbing the ratable or point-in-time paths:

1. **`usage_events` table** — append-only log of units consumed, each row owned by one obligation. Queue-style: `recognized_at IS NULL` means pending; set on pickup by the next recognition run.
2. **`consumption` pattern** — a new branch inside `compute_recognition` that computes a proportional delta from unprocessed units rather than elapsed days. Same function signature as the existing patterns, same return type.
3. **Two ingestion paths** — direct HTTP `POST /usage` (for customer apps or metering middleware), and Zuora `usage.uploaded` webhook via the existing M1 ingest-edge.

No changes to the M2a-1 scheduler, no changes to existing ratable/point-in-time behavior, no new async machinery.

## Data Model

### Migration 0014 — Extend `revrec.performance_obligations`

Three new columns + updated CHECK constraints:

```sql
ALTER TABLE revrec.performance_obligations
  ADD COLUMN units_total   BIGINT NULL,
  ADD COLUMN unit_label    TEXT   NULL,
  ADD COLUMN external_ref  TEXT   NULL;

ALTER TABLE revrec.performance_obligations
  DROP CONSTRAINT ck_perf_obligations_pattern;

ALTER TABLE revrec.performance_obligations
  ADD CONSTRAINT ck_perf_obligations_pattern
    CHECK (pattern IN ('ratable_daily', 'point_in_time', 'consumption'));

ALTER TABLE revrec.performance_obligations
  ADD CONSTRAINT ck_perf_obligations_consumption_units
    CHECK (pattern <> 'consumption' OR units_total IS NOT NULL);

-- The existing period CHECK rejects consumption obligations with no end_date.
-- Extend it to allow consumption as a second "end_date may be null" pattern.
ALTER TABLE revrec.performance_obligations
  DROP CONSTRAINT ck_perf_obligations_period;

ALTER TABLE revrec.performance_obligations
  ADD CONSTRAINT ck_perf_obligations_period
    CHECK (
      pattern IN ('point_in_time', 'consumption')
      OR (end_date IS NOT NULL AND end_date >= start_date)
    );

ALTER TABLE revrec.performance_obligations
  ADD CONSTRAINT uq_performance_obligations_external_ref
    UNIQUE (external_ref);
```

- `units_total`: the committed quantity (e.g., 1,000,000 API calls). Required when `pattern = 'consumption'`; null otherwise.
- `unit_label`: display-only string ("API calls", "GB", "seats"). Zero accounting impact.
- `external_ref`: identifier that upstream systems use to refer to this obligation. Populated by the Zuora usage webhook handler (path C). Nullable, unique when set. Analogous to `contracts.external_ref`.

### Migration 0015 — New `revrec.usage_events` table

```sql
CREATE TABLE revrec.usage_events (
  id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  obligation_id       UUID        NOT NULL REFERENCES revrec.performance_obligations(id) ON DELETE RESTRICT,
  units               BIGINT      NOT NULL CHECK (units > 0),
  occurred_at         TIMESTAMPTZ NOT NULL,
  received_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  idempotency_key     TEXT        NOT NULL UNIQUE,
  source              TEXT        NOT NULL CHECK (source IN ('api', 'zuora')),
  source_event_id     UUID        NULL REFERENCES inbox.source_events(id),
  recognized_at       TIMESTAMPTZ NULL,
  recognition_run_id  UUID        NULL REFERENCES revrec.recognition_runs(id)
);
CREATE INDEX ix_usage_events_obligation ON revrec.usage_events(obligation_id);
CREATE INDEX ix_usage_events_pending
  ON revrec.usage_events(obligation_id)
  WHERE recognized_at IS NULL;
```

- `units > 0` enforced at the DB. Negative adjustments are out of scope; later sub-milestones can add a credit-note pattern.
- `occurred_at` is what the upstream caller reports (when the usage happened). `received_at` is when FinLedger saw the event. Both stored for drill-down and late-event reporting.
- `idempotency_key UNIQUE` catches duplicate POSTs at the DB level. For the API path the caller supplies the key; for the Zuora path the handler derives it as `zuora:{source_event_id}`.
- `recognized_at` is the sentinel. NULL = pending pickup. Set by the recognition run in the same transaction that inserts the run's `recognition_events` audit rows.
- Partial index on `(obligation_id) WHERE recognized_at IS NULL` keeps the scheduler's pickup query cheap even as the history grows.

## Compute Logic

A new branch inside `core/src/finledger/revrec/compute.py`:

```python
@dataclass(frozen=True)
class ObligationSnapshot:
    # existing fields
    total_amount_cents: int
    start_date: date
    end_date: date | None
    pattern: str
    # new
    units_total: int | None


def compute_recognition(
    obligation: ObligationSnapshot,
    already_recognized_cents: int,
    already_recognized_through: date | None,
    run_through_date: date,
    unprocessed_units: int = 0,   # new param, ignored for ratable/point_in_time
) -> RecognitionDelta | None:
    if obligation.pattern == "point_in_time":
        return _compute_point_in_time(...)
    if obligation.pattern == "ratable_daily":
        return _compute_ratable_daily(...)
    if obligation.pattern == "consumption":
        return _compute_consumption(
            obligation, already_recognized_cents,
            unprocessed_units, run_through_date,
        )
    raise ValueError(f"unknown pattern: {obligation.pattern}")


def _compute_consumption(
    o: ObligationSnapshot,
    already_cents: int,
    unprocessed_units: int,
    run_through_date: date,
) -> RecognitionDelta | None:
    if unprocessed_units <= 0:
        return None
    assert o.units_total is not None and o.units_total > 0
    # Proportional drain
    proposed = (unprocessed_units * o.total_amount_cents) // o.units_total
    # Cap at remaining commitment (ASC 606: never over-recognize)
    remaining = o.total_amount_cents - already_cents
    amount = min(proposed, remaining)
    if amount <= 0:
        return None
    return RecognitionDelta(
        recognized_cents=amount,
        recognized_through=run_through_date,
    )
```

The `compute_recognition` signature gains one new keyword parameter with a default of 0. Existing callers for ratable and point_in_time are unaffected.

Unit tests cover:
- Zero unprocessed units → None
- Partial drain (50% consumed → 50% of commitment recognized)
- Full drain at cap
- Over-cap: 120% of commitment → recognition caps at commitment
- Already fully recognized + new events → None
- Rounding: 7 events × 143 units against 1000 units_total / $100 → exact cents across 7 events

## Engine Changes

`run_recognition` in `core/src/finledger/revrec/engine.py` today reads each active obligation, calls `compute_recognition`, aggregates the delta into a per-day journal entry, and records `recognition_events` rows. For consumption obligations it adds:

1. **Before** calling compute, load all `usage_events WHERE obligation_id = X AND recognized_at IS NULL`. Collect event IDs and sum `units`.
2. Pass the sum as `unprocessed_units` into `compute_recognition`.
3. **After** `post_entry` succeeds for the run, `UPDATE revrec.usage_events SET recognized_at = now(), recognition_run_id = :run_id WHERE id IN :picked_up_ids`.

All three steps live inside the same transaction as the existing journal-entry post, so partial state can't leak: a rollback rolls back the JE, the recognition_events rows, and the usage event pickups together.

Idempotency is preserved: if a completed run exists for `run_through_date` (the M2a-1 check), `run_recognition` returns that run without re-processing usage events.

## Ingestion

### Path A — Direct HTTP `POST /usage`

Single-event endpoint in `core/src/finledger/ui/routes/revrec.py`:

```
POST /usage
Content-Type: application/json
{
  "obligation_id": "<uuid>",
  "units": 1500,
  "occurred_at": "2026-04-21T10:30:00Z",
  "idempotency_key": "customer-app-event-abc123"
}
```

Responses:
- `201 Created` → `{"id": "<uuid>", "received_at": "..."}`
- `409 Conflict` on duplicate `idempotency_key` (catches `UniqueViolation` from DB)
- `404 Not Found` if obligation doesn't exist
- `422 Unprocessable Entity` if obligation's `pattern != 'consumption'`, or units <= 0, or `occurred_at` in the future (> now + 5 min clock skew allowance)

The handler is a thin wrapper: validate pattern, insert row, return. No recognition posting — that's the scheduler's job.

Bulk ingestion (POST an array of events) is deliberately out of scope for 1.5a. Clients can loop; most metering middlewares emit one-at-a-time anyway. A bulk endpoint lands when CSV import lands.

### Path C — Zuora `usage.uploaded` webhook

The M1 ingest-edge already receives Zuora webhooks, verifies HMAC, and inserts into `inbox.source_events`. The posting engine (`core/src/finledger/posting/engine.py`) then dispatches by `(source, event_type)` to a mapper that returns `LineSpec` rows for a journal entry.

Usage events don't post a journal entry directly — they accumulate in `usage_events` for the next daily recognition run. So the dispatch needs a new branch for *non-posting handlers*:

```python
NON_POSTING_HANDLERS = {
    ("zuora", "usage.uploaded"): from_zuora_usage,
}

async def process_one(session, event):
    key = (event.source, event.event_type)
    if key in NON_POSTING_HANDLERS:
        await NON_POSTING_HANDLERS[key](session, event.payload, event.id)
        event.processed_at = datetime.now(timezone.utc)
        await session.flush()
        return True
    # existing mapper dispatch continues unchanged
```

The handler lives in `core/src/finledger/revrec/usage_genesis.py`:

```python
async def from_zuora_usage(session, payload: dict, source_event_id: uuid.UUID) -> None:
    rate_plan_charge_id = payload.get("ratePlanChargeId")
    quantity = payload.get("quantity")
    start_date = payload.get("startDateTime")
    if not (rate_plan_charge_id and quantity and start_date):
        log.info("zuora usage event missing required fields; skipping")
        return
    obligation = await session.execute(
        select(PerformanceObligation).where(
            PerformanceObligation.external_ref == rate_plan_charge_id
        )
    ).scalar_one_or_none()
    if obligation is None:
        log.info(f"no obligation matches rate_plan_charge_id={rate_plan_charge_id}; skipping")
        return
    if obligation.pattern != "consumption":
        log.warn(f"zuora usage event for non-consumption obligation; skipping")
        return
    session.add(UsageEvent(
        id=uuid.uuid4(),
        obligation_id=obligation.id,
        units=int(quantity),
        occurred_at=_parse_datetime(start_date),
        received_at=datetime.now(timezone.utc),
        idempotency_key=f"zuora:{source_event_id}",
        source="zuora",
        source_event_id=source_event_id,
    ))
```

The `external_ref` column added in migration 0014 is the mapping point. During obligation creation (either via POST API or via M2a-1's Zuora invoice genesis), callers can set `external_ref` to the Zuora rate plan charge id. If not set, Zuora usage events for that obligation simply won't match and will be skipped (with an INFO log).

## API Additions

Existing `POST /revrec/contracts/{id}/obligations` extended:

```json
{
  "description": "API calls commitment",
  "pattern": "consumption",
  "start_date": "2026-01-01",
  "end_date": null,
  "total_amount_cents": 1200000,
  "units_total": 1000000,
  "unit_label": "API calls",
  "external_ref": "zuora-rpc-abc123"
}
```

Validation added:
- If `pattern == "consumption"`: `units_total` required and `> 0`; `end_date` optional (consumption obligations aren't time-bound in the same sense — M2a-1.5a doesn't enforce end_date but accepts it for display).
- If `pattern != "consumption"` and `units_total` provided → 422 (prevents accidental misconfiguration).

New endpoint: `POST /usage` as described above.

No changes to `POST /run` — it continues to trigger `run_recognition`, which now handles consumption obligations alongside ratable/point_in_time.

## UI Changes

**Contract detail page** — when a contract has any consumption obligation, its obligation card shows:
- The existing $ recognized/deferred progress bar
- A new units-consumed/committed progress bar below it
- `unit_label` displayed next to the unit counts
- A collapsed section with the last 10 usage events (expand to see more)

**New page `/revrec/usage`** — flat usage events table with filters:
- Columns: occurred_at, received_at, obligation (linked), units, source, status (pending/recognized), recognition run (linked when recognized)
- Filters: obligation, date range, source (api/zuora), status
- Added to nav under Revenue (sub-item, or secondary link in the Revenue page header)

**Waterfall** — consumption obligations contribute to backlog as `(total_amount_cents - recognized_cents)`. Since we can't forecast when the remaining units will land, their remaining backlog collapses to a single cell: current month. This is honest (we don't know) rather than guessing. Later milestones can add usage-rate projections.

**KPI pillars** — no changes. Total backlog, next 3 months, beyond — consumption remaining flows through the same aggregation.

## Data Flow

```
Customer app               Zuora metering
      │                           │
      │ POST /usage               │ webhook (signature-verified)
      ▼                           ▼
                          inbox.source_events (hash-chained, M1)
                                  │
                                  ▼
                          posting.engine.process_one
                                  │
                           key in NON_POSTING_HANDLERS?
                                  │
                                  ▼
                          from_zuora_usage (lookup by external_ref)
      │                           │
      └─────────────┬─────────────┘
                    ▼
           revrec.usage_events  (recognized_at = NULL)

---- Daily, separately (scheduler or on-demand) ----

run_recognition(through_date)
      │
      ├── for each consumption obligation:
      │     load pending usage_events, sum units
      │     compute_recognition(..., unprocessed_units=N)
      │
      ├── aggregate lines by (account, side)         [M2a-1, unchanged]
      ├── post_entry (one JE per run)                 [M2a-1, unchanged]
      ├── insert revrec.recognition_events rows       [M2a-1, unchanged]
      └── UPDATE usage_events SET recognized_at=now() WHERE id IN picked_up
```

## Error Handling

| Condition | Behavior |
|---|---|
| Duplicate `idempotency_key` on POST | 409 Conflict (DB UNIQUE constraint) |
| Obligation not found on POST | 404 |
| Obligation pattern != 'consumption' on POST /usage | 422 |
| units <= 0 on POST | 422 (before DB); redundant CHECK at DB |
| `occurred_at` in the future beyond 5-min skew | 422 |
| Obligation created with pattern='consumption' but no units_total | 422 (API); redundant CHECK at DB |
| Obligation fully recognized, more events arrive | Events inserted, recognized_at set by next run, $0 contribution |
| Zuora usage event, no obligation matches `external_ref` | Log at INFO, skip cleanly. Inbox event still marked processed |
| Zuora usage event for non-consumption obligation | Log at WARN, skip |
| Recognition run DB error mid-processing | Transaction rolls back JE + recognition_events + usage_events recognition mark — safe to retry |

## Testing Strategy

### Unit (`tests/unit/test_revrec_compute.py` extensions)
- `_compute_consumption`: zero units, partial drain, full drain, over-cap, already fully recognized returns None
- Rounding: 7 events × 143 units against `(1000 units_total, $100 total)` → sum of recognition exactly $100 after 8th event pushes past cap
- Proportional arithmetic: `(unprocessed * total) // units_total` never exceeds `remaining = total - already`

### Integration (`tests/integration/test_revrec_consumption.py` new file)
- POST /usage creates a pending event; idempotency_key UNIQUE is enforced
- 409 on duplicate idempotency_key
- 404 on unknown obligation
- 422 on pattern mismatch
- Seed consumption obligation, POST 3 usage events, run recognition → 1 JE posted with correct amount, all 3 events have `recognized_at` set
- Over-cap: POST events totaling 120% of commitment → recognition caps at `total_amount_cents`, surplus events still marked recognized with JE contribution of 0 on the cap-exceeding run
- Mixed-pattern run: a contract with one ratable + one consumption obligation → one aggregated JE per day covers both

### Integration — Zuora path (`tests/integration/test_revrec_consumption_zuora.py` new file)
- Zuora usage webhook with matching `ratePlanChargeId` → usage_event inserted with source='zuora'
- Zuora usage webhook with unmatched id → logged skip, no usage_event, inbox marked processed
- Zuora usage event for ratable obligation (pattern mismatch) → logged skip
- End-to-end: Zuora invoice (sets external_ref) → Zuora usage (matches by external_ref) → recognition run → correct revenue posted

### Property (`tests/property/test_revrec_consumption_invariants.py` new file)
- For any random sequence of consumption obligations and usage events: trial balance remains zero
- Total recognized for an obligation never exceeds its `total_amount_cents`, regardless of usage event sequence
- Sum of all events' units ≥ 0

## Migration Plan

Two new migrations:
- `0014_revrec_obligation_consumption_fields.py` — extends performance_obligations
- `0015_revrec_usage_events.py` — creates usage_events table with indexes

Both independent; rollback drops them in reverse order. No data migration needed (new columns are nullable, new table is empty on first deploy).

## File Layout

```
core/src/finledger/
  revrec/
    compute.py                    # extend: _compute_consumption + dispatch
    engine.py                     # extend: usage_events pickup + mark-recognized
    usage_genesis.py              # NEW: from_zuora_usage handler
  models/
    revrec.py                     # extend: new cols on PerformanceObligation,
                                  #         new UsageEvent model
  posting/
    engine.py                     # extend: NON_POSTING_HANDLERS dispatch
  ui/routes/
    revrec.py                     # extend: POST /usage, GET /usage, contract
                                  #         detail + obligation listing
                                  #         accept pattern='consumption'
  ui/templates/
    revrec_contract_detail.html   # extend: consumption progress + events section
    revrec_usage.html             # NEW: usage events page
core/alembic/versions/
  0014_revrec_obligation_consumption_fields.py
  0015_revrec_usage_events.py
core/tests/
  unit/test_revrec_compute.py                     # extend
  integration/test_revrec_consumption.py          # NEW
  integration/test_revrec_consumption_zuora.py    # NEW
  property/test_revrec_consumption_invariants.py  # NEW
```

## Scope Impact

Estimated ~2 weeks of focused work. ~800 LOC + 2 migrations + ~25 tests. Does not modify any existing M1 code paths; extends only M2a-1 compute / engine / API / models / UI. Ratable and point_in_time obligations are entirely unaffected.

## Future Milestones (Out of Scope)

- **M2a-1.5b** — Pay-as-you-go (no prior commitment). New pattern or mode that recognizes usage events immediately as revenue, no deferred revenue involved. Reuses `usage_events` and `POST /usage` infrastructure from this milestone.
- **M2a-1.5c** — Hybrid commitment + overage flag. Computes `max(0, sum(units) - units_total)` per obligation, surfaces overage KPI and break list, emits `overage_detected` events for downstream billing systems (FinLedger itself does not invoice). Builds on 1.5a and 1.5b.
- **CSV batch import of usage**. New endpoint `POST /usage/bulk` or operator UI for uploading CSVs. Writes to the same `usage_events` table; no new recognition logic.
- **Usage-rate projections in waterfall**. Replace the "all remaining in current month" collapse with a projection based on recent usage velocity. Requires a model decision (linear extrapolation, seasonality, etc.).
- **Negative adjustments / credit notes**. Reversing usage (customer returned units, billing correction). Needs a second event pattern and updated recognition semantics.
- **Tiered pricing**. First N units at price X, next M at price Y. Would extend the obligation model with a `tiers` JSONB and rework `_compute_consumption`.
