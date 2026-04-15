# FinLedger

A working reference implementation of a SaaS finance system. Stripe and Zuora webhooks enter through a Node/TS edge, land in a hash-chained source-event inbox, are posted by a Python engine into a double-entry ledger (enforced by DB triggers), and are reconciled against Stripe — all viewable on an HTMX dashboard. A pluggable GL exporter writes CSV journal files now; SAP/Oracle/NetSuite connectors slot into the same seam later.

See `docs/superpowers/specs/2026-04-14-finledger-design.md` for the full design, and `docs/superpowers/plans/2026-04-14-finledger-m1.md` for the M1 build plan.

## What M1 demonstrates

- **At-least-once-safe webhook ingestion** — Stripe signature verification, idempotent inbox insert by `(source, external_id)`, hash-chained for tamper detection.
- **Double-entry ledger** — `debits = credits` enforced by PostgreSQL CHECK trigger, posted entries immutable by trigger.
- **Posting engine** — maps source events to balanced journal entries; crash-safe (unprocessed rows retried); unknown event types parked with error.
- **Stripe↔Ledger reconciliation** — matches by `external_ref = stripe charge id`; reports matched/unmatched/mismatched with persistent break records.
- **Pluggable GL export** — `JournalExporter` protocol + `CsvJournalExporter` aggregates period journals to CSV with sha256 audit trail. SAP/Oracle connectors are M2 drop-ins.
- **Property-based tests** — `trial balance == 0` invariant holds under randomized event sequences; inbox replay is deterministic.

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
    core/            Python FastAPI + posting engine + recon + UI + GL export
    docs/            specs + plans + task RFCs
    fixtures/        sample webhook payloads for tests
