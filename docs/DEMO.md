# FinLedger Demo Walkthrough

End-to-end tour of what FinLedger does today. Runs in Docker, no cloud accounts needed.

After this you'll have:
- 2 ingested webhooks (Stripe charge + Zuora invoice) producing journal entries
- 5 revenue contracts across 4 ASC 606 recognition patterns
- A recognition run that posted ~$50k of revenue
- A working Stripe↔Ledger reconciliation
- Browsable admin UI at `http://localhost:8003`

## 1. Bring up the stack

```bash
git clone https://github.com/ypratap11/finledger
cd finledger
docker compose -f docker-compose.full.yml up --build
```

Wait ~40 seconds for Postgres health check + migrations + seed scripts. The compose file runs `alembic upgrade head`, then `seed_demo.py` (M1 ledger sample), then `seed_revrec_demo.py` (5 revrec contracts), then starts uvicorn.

Open <http://localhost:8003>.

## 2. Tour the UI

| URL | What you see |
|---|---|
| `/` | Inbox: 2 source events from the M1 seed (Stripe charge, Zuora invoice), both processed |
| `/journal` | Journal entries — 2 from the seed posting + 1 aggregated revrec recognition entry |
| `/recon` | Reconciliation: 1 matched + 1 unmatched break demonstrating the recon flow |
| `/flow` | Pipeline KPI dashboard |
| `/revrec` | Revenue waterfall: 12-month projection grouped by Backlog / Next-3 / Beyond |
| `/revrec/contracts` | All 5 contracts: ACME (ratable), Globex (ratable), Initech (future), Umbrella (consumption), Soylent (PAYG) |
| `/revrec/contracts/<id>` | Per-contract detail: progress bar for ratable, units/total bar for prepaid consumption, three stat tiles + per-unit rate for PAYG |
| `/revrec/runs` | Recognition log — one run from the seed, showing obligations processed and dollars recognized |
| `/revrec/usage` | Raw usage events feed (4 from Umbrella prepaid consumption + 3 from Soylent PAYG) |

## 3. The four ASC 606 Step 5 recognition patterns, side by side

| Pattern | Seed example | Trigger | JE on recognition |
|---|---|---|---|
| `ratable_daily` | ACME annual sub, $120k over 365 days | scheduled / on-demand | DR Deferred Rev / CR Revenue (daily prorate) |
| `point_in_time` | (not in seed; e.g. perpetual license) | scheduled / on-demand | DR Deferred Rev / CR Revenue (full at start) |
| `consumption` | Umbrella, $50k commitment / 5M API calls | usage event drives it | DR Deferred Rev / CR Revenue (units × price-per-commitment, capped) |
| `consumption_payg` | Soylent, $0.01/call, no commitment | usage event drives it | DR **Unbilled AR** / CR Revenue (units × per-unit rate, no cap) |

The recognition engine is a single function that handles all four. Mixed runs (ratable + consumption + PAYG together) coalesce into one balanced journal entry.

## 4. End-to-end flow (curl)

The seed already produced data, but you can drive the full loop yourself.

### 4a. Send a Stripe webhook → journal entry

The Node ingest-edge service runs at `:8002`. Stripe webhook signing is bypassed in dev with `STRIPE_WEBHOOK_SECRET=whsec_test`:

```bash
curl -X POST http://localhost:8002/webhooks/stripe \
  -H "Content-Type: application/json" \
  -H "Stripe-Signature: t=1,v1=test" \
  --data @fixtures/stripe_charge_succeeded.json
```

Then `POST /run` on the posting engine (it auto-runs in the background, but you can force it):

```bash
curl -X POST http://localhost:8003/journal/post-pending
```

Inspect at `/journal` — new entry posted with DR Cash / CR AR.

### 4b. Send a Zuora invoice → contract auto-generated → recognition

```bash
curl -X POST http://localhost:8002/webhooks/zuora \
  -H "Content-Type: application/json" \
  --data '{
    "eventType": "invoice.posted",
    "invoice": {
      "id": "INV-DEMO-1",
      "invoiceNumber": "I-DEMO-1",
      "accountId": "ACC-DEMO",
      "amount": 60000,
      "currency": "USD",
      "metadata": {
        "service_period_start": "2026-05-01",
        "service_period_end": "2026-07-31"
      }
    }
  }'
```

The posting engine creates a journal entry (DR AR / CR Deferred Revenue), then `from_zuora_invoice` genesis auto-creates a contract + ratable obligation because the invoice carries `service_period_*` metadata. Open `/revrec/contracts` and you'll see the new contract.

Trigger recognition through today:

```bash
curl -X POST http://localhost:8003/revrec/run \
  -H "Content-Type: application/json" \
  -d '{"through_date": "'$(date +%Y-%m-%d)'"}'
```

A new recognition run appears at `/revrec/runs` with the daily-prorated revenue.

### 4c. Pay-as-you-go usage event → revenue accrues to Unbilled AR

Find Soylent's obligation id from the UI (or query):

```bash
SOYLENT_OBL=$(docker exec finledger-postgres-1 psql -U finledger -d finledger -tA -c \
  "SELECT id FROM revrec.performance_obligations WHERE pattern='consumption_payg'")

curl -X POST http://localhost:8003/revrec/usage \
  -H "Content-Type: application/json" \
  -d "{
    \"obligation_id\": \"$SOYLENT_OBL\",
    \"units\": 25000,
    \"occurred_at\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
    \"idempotency_key\": \"demo-payg-extra-1\"
  }"
```

Run recognition again. The PAYG obligation accrues `25000 × $0.01 = $250` of revenue, debited to `1500-UNBILLED-AR` (the contract asset).

Visit `/revrec/contracts/<soylent-id>` — the PAYG tile updates.

### 4d. Bill the unbilled AR (admin fallback)

When Zuora later invoices the consumed usage, FinLedger reclassifies Unbilled AR → AR. The Zuora-driven path uses `metadata.payg_obligation_ref` on `invoice.posted`. Demo via the admin endpoint:

```bash
curl -X POST http://localhost:8003/revrec/obligations/$SOYLENT_OBL/bill \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_amount_cents": 1700,
    "period_start": "2026-04-01",
    "period_end": "2026-04-30",
    "external_ref": "INV-SOYLENT-APR-2026"
  }'
```

This posts DR `1200-AR` / CR `1500-UNBILLED-AR` for $17, drains the unbilled balance by that amount. The contract detail page now shows the Recognized split: some unbilled, some billed.

### 4e. Run reconciliation

```bash
# Recon UI shows the existing seeded run; new runs live at:
curl http://localhost:8003/recon
```

### 4f. Export the journal as CSV

```bash
curl http://localhost:8003/journal/export.csv > journal.csv
head journal.csv
```

## 5. Verify the books are balanced

After all the above, trial balance should still be at zero:

```bash
docker exec finledger-postgres-1 psql -U finledger -d finledger -c "
  SELECT
    sum(CASE WHEN side='debit' THEN amount_cents ELSE 0 END) AS debits,
    sum(CASE WHEN side='credit' THEN amount_cents ELSE 0 END) AS credits
  FROM ledger.journal_lines"
```

`debits` and `credits` are always equal — enforced by a Postgres trigger on `journal_entries`, not application code.

## 6. Verify the source-of-truth chain

Every `inbox.source_events` row carries a SHA-256 hash chain. Tampering with a row breaks the chain:

```bash
docker exec finledger-postgres-1 psql -U finledger -d finledger -c "
  SELECT count(*) AS events,
    encode(MAX(row_hash), 'hex') AS chain_tip
  FROM inbox.source_events"
```

Or run the verification job:

```bash
docker exec finledger-core-1 python -c "
import asyncio
from finledger.ingest.verify import verify_chain
asyncio.run(verify_chain())
"
```

## 7. Tear down

```bash
docker compose -f docker-compose.full.yml down -v
```

The `-v` removes the postgres volume so the next bring-up reseeds from scratch.

---

## How to use FinLedger in your own setup

**To send real Stripe events:** point your Stripe webhook (Dashboard → Developers → Webhooks) at `https://your-host/webhooks/stripe`. Set `STRIPE_WEBHOOK_SECRET` in `ingest-edge` env. The signature verification is real.

**To wire Zuora:** Zuora can send `invoice.posted` and `usage.uploaded` to `https://your-host/webhooks/zuora`. Add `service_period_start`/`end` metadata to invoices to auto-create ratable obligations; add `payg_obligation_ref` metadata to invoices that should reclassify Unbilled AR (so revenue isn't double-recognized).

**To define obligations directly:** `POST /revrec/contracts` then `POST /revrec/contracts/{id}/obligations` with the pattern of your choice. See `core/tests/integration/test_revrec_api.py` for canonical request bodies for each pattern.

**To export to your ERP:** the `JournalExporter` Protocol in `core/src/finledger/gl/` is the seam. Today there's a CSV exporter; SAP/Oracle/NetSuite plug in here. M3 milestone target.

**To embed the schedule in production:** `python -m finledger.workers.revrec_scheduler` runs daily recognition; cron it or run it in a sidecar.
