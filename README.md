# FinLedger

[![CI](https://github.com/ypratap11/finledger/actions/workflows/ci.yml/badge.svg)](https://github.com/ypratap11/finledger/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

**Created and maintained by [Pratap Yeragudipati](https://github.com/ypratap11).**

An open-source SaaS finance pipeline. Stripe and Zuora webhooks enter through a Node/TS edge, land in a hash-chained source-event inbox, are posted by a Python engine into a double-entry ledger (enforced by Postgres triggers), and are reconciled against the source — all viewable on an HTMX dashboard. An ASC 606 revenue-recognition engine drains deferred revenue over time. A pluggable GL exporter writes CSV journal files today; SAP/Oracle/NetSuite connectors slot into the same seam later.

![Revenue waterfall](docs/images/revrec-waterfall.png)

See `docs/superpowers/specs/2026-04-14-finledger-design.md` for the full design, and `docs/superpowers/plans/` for the implementation plans (M1, M2a-1).

## One-command quickstart

```bash
git clone https://github.com/ypratap11/finledger.git
cd finledger
docker compose -f docker-compose.full.yml up --build
```

Then open **http://localhost:8003/** — postgres, migrations, demo seed data, the Python UI, and the Node ingest-edge all come up together.

## What M1 demonstrates

- **At-least-once-safe webhook ingestion** — Stripe signature verification, idempotent inbox insert by `(source, external_id)`, hash-chained for tamper detection.
- **Double-entry ledger** — `debits = credits` enforced by PostgreSQL CHECK trigger, posted entries immutable by trigger.
- **Posting engine** — maps source events to balanced journal entries; crash-safe (unprocessed rows retried); unknown event types parked with error.
- **Stripe↔Ledger reconciliation** — matches by `external_ref = stripe charge id`; reports matched/unmatched/mismatched with persistent break records.
- **Pluggable GL export** — `JournalExporter` protocol + `CsvJournalExporter` aggregates period journals to CSV with sha256 audit trail. SAP/Oracle connectors are M2 drop-ins.
- **Property-based tests** — `trial balance == 0` invariant holds under randomized event sequences; inbox replay is deterministic.

## What M2a-1 adds (ASC 606 Step 5)

- **Contracts + performance obligations.** Auto-created from Zuora `invoice.posted` events that carry `metadata.service_period_start` / `service_period_end`, with an admin fallback API (`POST /revrec/contracts`, `POST /revrec/contracts/{id}/obligations`) for one-off cases.
- **Recognition engine.** Ratable (daily accrual) + point-in-time patterns. On-demand trigger (`POST /revrec/run`) or daily scheduled job (`python -m finledger.workers.revrec_scheduler`). One aggregated journal entry per run (DR Deferred Revenue / CR Revenue); per-obligation audit trail in `revrec.recognition_events`.
- **Waterfall view.** 12-month projection at `/revrec` with Backlog / Next-3 / Beyond pillars, contract detail pages with recognized/deferred progress bars, and a chronological recognition log.
- **Editorial-finance UI.** Fraunces display type, bone/cream paper surface, hairline rules, JetBrains Mono tabular numerics — distinct from the M1 utilitarian dashboard because revrec is the long-form analytical surface.
- **Property invariants.** Full recognition over random obligation sets keeps trial balance at zero AND recognizes exactly the contracted total.

See `docs/superpowers/specs/2026-04-16-m2a-1-revrec-design.md` for the full design.

M2a-2 (SSP allocation + contract modifications) and M2a-3 (variable consideration + constraint) are planned follow-ups. Consumption-based recognition is M2a-1.5.

## What M2a-1.5a adds (committed usage drain)

- **New `consumption` recognition pattern.** Obligations now support a usage-based pattern alongside ratable and point-in-time. Recognition drains deferred revenue proportional to units consumed, capped at the contract price (ASC 606: never over-recognize).
- **`usage_events` table.** Append-only log of units consumed per obligation, with idempotency keys, `occurred_at` vs `received_at` tracking, and a pending-queue sentinel (`recognized_at IS NULL`) for the scheduler to drain.
- **Two ingestion paths.** Direct HTTP `POST /revrec/usage` for customer apps and metering middleware; Zuora `usage.uploaded` webhook via a non-posting handler in the M1 posting engine. Both write to the same table.
- **Contract-level consumption view.** `/revrec/contracts/{id}` shows units-consumed vs committed with a progress bar and a collapsed mini-table of recent events.
- **`/revrec/usage` page.** Flat list of all usage events with status pill (pending / recognized).
- **Waterfall integration.** Consumption obligations contribute their remaining `total_amount_cents - recognized_cents` to the current-month bucket (no future projection yet — usage-rate forecasts land in a later milestone).

See `docs/superpowers/specs/2026-04-21-m2a-1-5a-consumption-drain-design.md` for the full design.

Still to come: **M2a-1.5b** (pay-as-you-go, no commitment), **M2a-1.5c** (overage flagging + hybrid), CSV batch import of usage, and usage-rate projection in the waterfall.

## What M2a-1.5b adds (pay-as-you-go usage)

- **New `consumption_payg` recognition pattern.** Usage-based contracts with no upfront commitment. Revenue accrues at a flat per-unit rate as units are consumed, capped only by what's actually used (no commitment, no over-recognition risk).
- **Unbilled AR accrual.** PAYG recognition posts DR `1500-UNBILLED-AR` (Contract Asset) / CR Revenue. The unbilled AR account is configurable per obligation in case different products want different contract-asset accounts.
- **Billing reclassification.** When Zuora's `invoice.posted` carries `metadata.payg_obligation_ref` matching a `consumption_payg` obligation, FinLedger's posting engine rewrites the credit account from Deferred Revenue to that obligation's Unbilled AR account — moving the balance from contract-asset to billed AR without double-recognizing revenue.
- **Admin bill fallback.** `POST /revrec/obligations/{id}/bill` for cases where the Zuora-driven path isn't available; idempotent on `external_ref`.
- **Per-obligation tracking.** New `revrec.payg_reclassifications` table records every Unbilled→Billed AR move. Contract detail page shows the Recognized split (unbilled vs billed) plus a per-unit rate and the recent-events disclosure shared with prepaid consumption.
- **Waterfall behavior.** PAYG obligations contribute zero to the 12-month projection (no commitment to project; usage-rate forecasting deferred).

See `docs/superpowers/specs/2026-04-24-m2a-1-5b-payg-recognition-design.md` for the full design.

## End-to-end demo

For a full walkthrough — bring up the stack, tour each UI surface, drive every flow with curl, exercise all four ASC 606 Step 5 recognition patterns — see [`docs/DEMO.md`](docs/DEMO.md). The shortest path:

```bash
docker compose -f docker-compose.full.yml up --build
# wait ~40s; open http://localhost:8003
```

Seed scripts auto-run and produce 5 contracts (ratable + prepaid consumption + PAYG), 7 usage events, 1 recognition run posting ~$50k of revenue.

## Run locally

    docker compose up -d postgres
    cd core && pip install -e '.[dev]' && alembic upgrade head
    .venv/Scripts/uvicorn finledger.ui.app:app --reload --port 8000 &

    cd ../ingest-edge && npm install
    STRIPE_WEBHOOK_SECRET=whsec_test npm run dev &

Visit `http://localhost:8000/` for the admin dashboard.

## Tests

    cd core
    pytest tests/unit
    pytest tests/integration
    pytest tests/property

## Known limitations in M1

- JSON canonicalization between Node and Python uses a recursive sorted-keys implementation on both sides, verified against Python's `json.dumps(sort_keys=True, separators=(",",":"))`. Cross-language hash-chain parity holds for nested payloads; there is no third-party canonical-JSON library in either stack for M1.
- M1 assumes `currency = USD` at the ledger invariant level. Multi-currency + FX comes in a later milestone.
- GL export is CSV-only. SAP FBDI / IDoc, Oracle FBDI, NetSuite SuiteTalk are M2.
- No rev rec, no Zuora↔Ledger recon, no approval workflow. M2/M3.

## What's next

- **M2** — Zuora sandbox integration, contracts + performance obligations, ASC 606 revenue schedules (ratable + consumption), rev waterfall view, Zuora↔Ledger recon, first real ERP connector (likely Oracle FBDI or NetSuite).
- **M3** — Auth + SOD approval workflow, second ERP connector, Ledger↔GL recon, hash-chain verify scheduled job.

## Layout

    ingest-edge/     Node/TS Fastify webhook edge (Stripe + Zuora)
    core/            Python FastAPI + posting engine + recon + revrec + UI + GL export
    docs/            specs + plans + task RFCs + screenshots
    fixtures/        sample webhook payloads for tests

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for quickstart, test instructions, code style, and how to file issues / submit PRs. Good-first-issue candidates: additional source adapters (Chargebee, Paddle, Maxio), additional GL exporters (NetSuite, SAP, Oracle), accessibility audit.

## License

Apache 2.0. See [LICENSE](LICENSE).
