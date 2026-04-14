# FinLedger — Design Spec

**Date:** 2026-04-14
**Status:** Approved for planning
**Author:** Pratap

## Tagline

A working reference implementation of a SaaS finance system: Stripe + Zuora ingestion → double-entry ledger → ASC 606 revenue recognition → GL export, with SOX-style controls and end-to-end reconciliation.

## Goals

Portfolio project demonstrating the core competencies from finance-systems engineering job descriptions: billing integrations, double-entry ledger, revenue recognition (ratable + consumption), SOX-style controls, and end-to-end reconciliation across Stripe, Zuora, and GL.

## Non-goals (M1)

- Multi-currency / FX conversion (schema-ready, logic deferred)
- Multi-entity / intercompany eliminations
- Tax engine integration (Avalara, Anrok, etc.)
- ASC 606 contract modifications
- Bundle SSP (standalone selling price) allocation across multi-element arrangements
- End-to-end browser tests
- Load / performance testing

Each of these is listed as "future work" in the README; knowing what is not solved is part of the signal.

## Decisions (with reasoning)

| # | Decision | Reasoning |
|---|----------|-----------|
| 1 | Combine billing→ledger (A) and quote-to-cash (B) into one quote-to-revenue pipeline | Single coherent narrative is stronger than two fragmented projects |
| 2 | New repo at `C:\Pratap\work\finledger` | Separation from OpenClaw work |
| 3 | Python core (FastAPI + SQLAlchemy + Postgres) + Node/TS Fastify webhook edge | Python is the language of finance eng; Node edge demonstrates correct split of concerns and polyglot maturity |
| 4 | Real Stripe test mode + real Zuora sandbox; CPQ and NetSuite mocked in-repo | Real signal where cheap; mocks where sandboxes are painful or nonexistent |
| 5 | ASC 606: ratable subscriptions + consumption/usage metering | Matches JD's "consumption-based billing"; ratable alone is table stakes |
| 6 | Ledger: source-event inbox + append-only double-entry journal | Auditors need source documents and accounting treatment as separate artifacts; this is how real finance systems are built |
| 7 | SOX controls: audit log + hash-chained immutability + segregation-of-duties approval workflow | JD explicitly names SOX; SOD is the move that proves understanding of internal controls vs. just logging |
| 8 | Admin UI: FastAPI + HTMX + Jinja, read-only plus approval queue | Demo-able without a separate build pipeline; HTMX is fast for read-heavy admin views |
| 9 | Three reconciliations: Stripe↔Ledger, Zuora↔Ledger, Ledger↔GL | Full "cash to GL" story; matching keys are designed into the ledger from day one |
| 10 | Milestones: M1 spine, M2 subs+rev rec, M3 controls+GL | Each milestone is independently demoable |
| 11 | Tests: unit + integration (real Postgres + fixtures) + property-based on ledger invariants | Property tests on double-entry invariants are the strongest possible signal for finance correctness |

## Architecture

```
Stripe (test) ──┐        CPQ-mock
Zuora (sandbox)─┤              │
                ▼              ▼
         ingest-edge     core API
         (Node/TS)      (Python)
              │              │
              └──────┬───────┘
                     ▼
              source_events (inbox, hash-chained)
                     │
                     ▼
              posting-engine
              /             \
     journal_entries    revenue_schedules
      (double-entry)       (ASC 606)
              \             /
               recon-engine
                     │
                     ▼
              gl-export → netsuite-mock

         admin-ui (FastAPI + HTMX + Jinja)
```

### Processes

1. **`ingest-edge`** (Node/TS, Fastify) — verifies webhook signatures, computes idempotency keys, writes to `source_events`, acks 200. One job, small surface area, isolated from Python boot latency.
2. **`core`** (Python, FastAPI) — posting-engine, rev rec, recon, GL export, admin UI. Background jobs via APScheduler.
3. **`cpq-mock`** (Python module in `core`) — routes under `/mock/cpq/*`, creates orders/subscriptions.
4. **`netsuite-mock`** (Python module in `core`) — accepts batched journal exports, returns export IDs.
5. **`postgres`** — single DB, schemas: `inbox`, `ledger`, `revrec`, `gl`, `audit`.

### Why one Postgres, not microservice DBs

Transactional integrity across inbox → ledger → revrec in a single DB transaction is the correct design for a ledger. Schemas give logical separation without distributed-transaction complexity.

## Data model

### `inbox` schema

```sql
source_events (
  id                uuid pk,
  source            text,          -- 'stripe' | 'zuora' | 'cpq'
  event_type        text,
  external_id       text,
  idempotency_key   text unique,
  payload           jsonb,         -- raw body, never modified
  received_at       timestamptz,
  prev_hash         bytea,
  row_hash          bytea,
  processed_at      timestamptz null,
  processing_error  text null,
  UNIQUE(source, external_id)
)
```

`prev_hash` + `row_hash` form a tamper-evident chain. A nightly `verify_chain` job re-hashes from genesis and alerts on break.

### `ledger` schema

```sql
accounts (
  id           uuid pk,
  code         text unique,       -- '1000-CASH', '2000-DEFERRED-REV'
  name         text,
  type         text,              -- asset | liability | equity | revenue | expense
  normal_side  text               -- debit | credit
)

journal_entries (
  id               uuid pk,
  source_event_id  uuid fk -> inbox.source_events null,  -- null for manual entries
  posted_at        timestamptz,
  status           text,          -- draft | pending_approval | posted | reversed
  preparer_id      uuid,
  approver_id      uuid null,
  reverses         uuid fk -> journal_entries null,
  memo             text
)

journal_lines (
  id             uuid pk,
  entry_id       uuid fk,
  account_id     uuid fk,
  side           text,            -- debit | credit
  amount_cents   bigint,
  currency       text,
  external_ref   text null,       -- stripe charge id, zuora invoice id (recon matching)
  dimension_json jsonb            -- customer_id, subscription_id, contract_id
)
```

Invariants enforced in the DB:
- CHECK trigger: `sum(debit) = sum(credit)` per `journal_entries` row after all lines inserted.
- Trigger: forbid UPDATE/DELETE on `journal_entries` or `journal_lines` where `status='posted'`.

Money is always `(amount_cents bigint, currency text)`. Never float.

### `revrec` schema

```sql
contracts (
  id                  uuid pk,
  customer_id         uuid,
  cpq_order_id        text,
  total_amount_cents  bigint,
  start_date          date,
  end_date            date
)

performance_obligations (
  id                uuid pk,
  contract_id       uuid fk,
  type              text,          -- subscription_ratable | usage_metered
  unit_price_cents  bigint null,
  total_cents       bigint,
  start_date        date,
  end_date          date
)

revenue_schedules (
  id                uuid pk,
  obligation_id     uuid fk,
  period_start      date,
  period_end        date,
  scheduled_cents   bigint,
  recognized_cents  bigint default 0,
  journal_entry_id  uuid null
)
```

Ratable flow: on contract signing, pre-compute all monthly schedule rows. Monthly cron moves deferred → revenue.
Consumption flow: usage events create schedule rows dynamically with immediate recognition (earn-as-consumed).

### `gl` schema

```sql
gl_exports (
  id                 uuid pk,
  batch_ref          text unique,
  period_start       date,
  period_end         date,
  journal_entry_ids  uuid[],
  exported_at        timestamptz,
  netsuite_mock_id   text,
  status             text           -- prepared | sent | acknowledged
)
```

### `audit` schema

```sql
audit_log (
  id           uuid pk,
  actor_id     uuid,
  action       text,
  entity_type  text,
  entity_id    uuid,
  before_json  jsonb null,
  after_json   jsonb null,
  at           timestamptz
)
```

## Python package layout (`core/`)

```
core/
  api/              FastAPI routers (webhooks handoff, admin)
  ingest/           source_events writer, hash chain
  posting/          source_event → journal entry mappers
  ledger/           account ops, entry posting, reversals
  revrec/           obligation builders, schedule generation, monthly recognition
  recon/            stripe↔ledger, zuora↔ledger, ledger↔gl matchers
  gl/               netsuite-mock client, batch preparation
  mocks/            cpq-mock, netsuite-mock HTTP routes
  ui/               Jinja templates + HTMX endpoints
  auth/             role model, SOD decorators
  jobs/             scheduler entry points
  tests/
    unit/
    integration/
    property/
```

## Node ingest-edge (`ingest-edge/`)

Fastify app, ~300 lines. Routes: `POST /webhooks/stripe`, `POST /webhooks/zuora`. Verifies signature, computes idempotency key, writes to `inbox.source_events` via direct Postgres client, returns 200. Deliberately does not call the core API — decoupling keeps the hot path fast and the edge independently deployable.

## End-to-end flow: annual subscription example

1. **Quote accepted (CPQ):** CPQ-mock emits `cpq.order.accepted` → `source_events` → posting-engine creates `contracts`, two `performance_obligations` (ratable + metered), 12 pre-computed `revenue_schedules` rows for the ratable. No journal entry yet.
2. **Zuora invoice posted:** `invoice.posted` → journal entry J-1: DR AR / CR Deferred Revenue. AR line carries Zuora invoice ID as `external_ref`.
3. **Stripe payment:** `charge.succeeded` → journal entry J-2: DR Cash / CR AR. Cash line carries Stripe charge ID; AR line carries the same Zuora invoice ID for recon symmetry.
4. **Usage event:** `usage.recorded` → creates a metered `revenue_schedules` row + journal entry J-3: DR AR / CR Revenue (recognize as consumed).
5. **Monthly rev rec job:** posts J-4 for each ratable schedule row in the period: DR Deferred / CR Revenue.
6. **SOD approval:** manual-only. Entries with `source_event_id IS NULL` enter `pending_approval`. Preparer != approver enforced at three layers.
7. **Nightly recon:** three jobs match by external_ref keys → produce `recon_runs` reports.
8. **Monthly GL export:** batches posted entries → `netsuite-mock` → stores `gl_exports` row. Next-day recon confirms.

## Error handling

| Class | Handling |
|-------|----------|
| Duplicate external event | UNIQUE on `idempotency_key` rejects; ingest acks 200 |
| Webhook ack failure | Same protection on retry |
| Posting crash mid-processing | `processed_at IS NULL` + retry worker; mapper runs in single DB tx |
| Unbalanced entry | DB CHECK trigger rejects; inbox row stays unprocessed; alerted |
| Out-of-order events | Mapper defensive; marks `processing_error='out_of_order'`; retry worker picks up later |
| Corrupt payload | Stored verbatim; flagged with `processing_error='unknown_event_type'`; admin review |
| Hash chain break | `verify_chain` nightly; alert + refuse to post until resolved |
| Recon mismatch | `recon_break` row; human correction via SOD-gated manual entry |
| Reversal | Never UPDATE/DELETE; new entry with `reverses` FK + opposite sides |
| FX (M1) | Assert `currency='USD'`; schema ready for multi-currency |
| Rev rec rounding | Decimal math, last period absorbs remainder; invariant tested |
| SOD bypass | App guard + DB CHECK + session check (three layers) |
| Clock/period boundary | Period attribution reads payload timestamp, never `now()` |

## Observability

- Correlation IDs: `source:external_id` on every log line.
- Inbox dashboard: received / processed / errored / stuck (>5 min) counts.
- Recon dashboard: open breaks by age.
- Health endpoint: red if hash chain invalid, stuck events >15 min, or posting queue depth exceeded.

## Testing strategy

Three layers:

### Unit (`tests/unit/`)
- Rev rec schedule generation (rounding, leap years, partial months)
- Hash chain computation determinism
- Stripe signature verification
- Mapper functions (payload → expected lines)
- SOD guard truth table

Target: ~200 tests, <5s.

### Integration (`tests/integration/`)
Real Postgres via docker-compose, Stripe/Zuora via recorded HTTP fixtures.
- Subscription lifecycle end-to-end
- Idempotency under duplicate webhook delivery
- Crash recovery (raise in mapper → retry processes)
- Reversal correctness (double-reverse is identity on balances)
- Hash chain break detection
- SOD enforcement (API + DB + session layers)
- Reconciliation with known deltas

Target: ~40 scenarios, <60s.

### Property-based (`tests/property/`)
Hypothesis strategies generate random event sequences; assert invariants:

- Trial balance: `sum(debits) == sum(credits)` always
- Accounting equation: `Assets = Liabilities + Equity + (Revenue - Expense)` always
- Reversal identity: double-reversing returns to prior state
- Inbox replay determinism: replaying source events into fresh DB reproduces ledger exactly
- Rev rec sum invariant: `sum(schedules) == obligation.total` exactly

Target: ~10 properties, 200+ examples each, <90s.

### CI

GitHub Actions: lint (ruff + mypy) → unit → integration (compose up) → property → migration drift check (`alembic check`).

## Milestones

### M1 — Billing→Ledger spine (2 weeks)

**Scope:**
- Node ingest-edge (Stripe + Zuora webhook receivers)
- `source_events` inbox with hash chain
- Posting-engine for Stripe `charge.succeeded` and Zuora `invoice.posted`
- Double-entry journal (accounts, entries, lines) with balance trigger
- Stripe↔Ledger reconciliation job
- Read-only admin dashboard: inbox view, journal view, recon view
- docker-compose for local run

**Demo:** "Stripe test-mode payment shows up in the ledger, reconciled, within one minute of the webhook."

**Not in M1:** rev rec, Zuora↔Ledger recon, SOD approvals, GL export.

### M2 — Subscriptions + revenue recognition (2 weeks)

- Full Zuora sandbox integration
- Contracts + performance obligations + revenue schedules
- Ratable rev rec monthly job
- Usage-metered consumption rev rec
- Zuora↔Ledger reconciliation
- Rev rec waterfall view in dashboard

**Demo:** "Annual subscription generates 12-month rev schedule; usage events immediately recognize revenue; dashboard shows the waterfall."

### M3 — Controls + GL export (1-2 weeks)

- Auth + roles (preparer, approver)
- SOD-gated manual journal entry workflow
- Approval queue UI
- NetSuite-mock GL export
- Ledger↔GL reconciliation
- Hash chain verify job + admin alert view

**Demo:** "Manual journal entry proposed by user A, approved by user B, batched into monthly GL export, reconciled the next day."

## Future work (documented, not built)

- Multi-currency with FX entries
- Multi-entity + intercompany eliminations
- Tax engine integration
- ASC 606 contract modifications
- Bundle SSP allocation
- Real NetSuite / Workday connectors
- Workato/MuleSoft-style connector framework with retry/DLQ/schema mapping (this would absorb FinLedger into a broader iPaaS demo)

## Implementation plan

M1 ships first and gets its own implementation plan (next document). M2 and M3 get separate specs and plans as M1 lands.
