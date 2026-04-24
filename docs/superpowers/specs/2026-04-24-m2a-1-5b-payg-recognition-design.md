# M2a-1.5b — Pay-As-You-Go Usage Recognition

**Status:** Design
**Date:** 2026-04-24
**Builds on:** M2a-1.5a (committed usage drain)
**Predecessor spec:** `2026-04-21-m2a-1-5a-consumption-drain-design.md`

## Summary

Add a second consumption pattern, `consumption_payg`, for usage-based contracts with **no upfront commitment**. Revenue recognizes per usage event at a flat per-unit rate, accruing to **Unbilled AR** (a contract asset) instead of draining deferred revenue. When Zuora later issues an invoice for the consumed usage, FinLedger reclassifies the obligation's accrued unbilled AR into billed AR — no double-recognition of revenue.

## Scope

**In scope:**
- New `consumption_payg` recognition pattern + per-unit pricing.
- Recognition JE: DR Unbilled AR / CR Revenue (per usage batch).
- Billing reclassification JE: DR AR / CR Unbilled AR (on Zuora `invoice.posted` for matching obligations, plus an admin fallback).
- Contract-detail UI surface for PAYG obligations (units consumed, recognized-unbilled, recognized-billed).
- New per-obligation tracking table for billing reclassifications.

**Out of scope (deferred):**
- Tiered pricing (flat rate only — multi-tier in M2a-1.5d or later).
- Hybrid commitment + overage (M2a-1.5c).
- Automated reconciliation between Zuora invoice amount and accumulated unbilled AR. MVP surfaces residuals visually for human inspection.
- Waterfall projection for PAYG obligations (no commitment to project; deferred until usage-rate forecasting lands).
- Invoice generation by FinLedger (Zuora remains the billing source-of-truth).

## Architecture

### Pattern choice
PAYG is added as a **new** pattern `consumption_payg`, sibling to the existing `consumption`. No reuse-via-NULL on the prepaid pattern, no separate obligation table — minimal extension, names the distinction, leaves room for hybrid contracts (M2a-1.5c) to reuse fields from both patterns on a single obligation.

### Data model

**Migration 0016** on `revrec.performance_obligations`:
- Add column `price_per_unit_cents INTEGER NULL`.
- Add column `unbilled_ar_account_code TEXT NOT NULL DEFAULT '1500-UNBILLED-AR'`.
- Extend `ck_perf_obligations_pattern` CHECK to include `'consumption_payg'`.
- Add CHECK `ck_perf_obligations_payg_price`:
  `(pattern <> 'consumption_payg') OR (price_per_unit_cents IS NOT NULL AND price_per_unit_cents > 0)`.
- Relax `ck_perf_obligations_consumption_units` so it only fires for `pattern = 'consumption'` (prepaid units commitment); PAYG has no commitment.
- Allow `total_amount_cents IS NULL` for PAYG (drop NOT NULL conditionally via CHECK; or keep NOT NULL and set 0 — settled at implementation: NULL with conditional CHECK, since "not applicable" is the real meaning).
- PAYG allowed with `end_date IS NULL` (open-ended), same as existing relaxation for `consumption` in 0014.

**Migration 0017** creates `revrec.payg_reclassifications`:
```
id                     UUID PRIMARY KEY
obligation_id          UUID NOT NULL REFERENCES revrec.performance_obligations(id)
amount_cents           BIGINT NOT NULL CHECK (amount_cents > 0)
invoice_external_ref   TEXT NULL
billed_at              TIMESTAMPTZ NOT NULL DEFAULT now()
journal_entry_id       UUID NOT NULL REFERENCES ledger.journal_entries(id)
source_event_id        UUID NULL REFERENCES inbox.source_events(id)
```
Index on `obligation_id`. Used to compute "Recognized (billed)" per obligation without modifying the existing `recognition_events` shape.

**Chart-of-accounts seed** adds `1500-UNBILLED-AR` ("Unbilled Accounts Receivable / Contract Asset", asset, normal-DR) to `seed_chart_of_accounts`.

**Model updates** (`finledger.models.revrec`):
- `PerformanceObligation.price_per_unit_cents: int | None`
- `PerformanceObligation.unbilled_ar_account_code: str` (default `'1500-UNBILLED-AR'`)
- New `PaygReclassification(Base)` matching the table.

### Recognition compute

`compute.py` extends `ObligationSnapshot` with `price_per_unit_cents: int | None = None` and adds dispatch for `consumption_payg`:

```python
def _compute_consumption_payg(o, unprocessed_units, run_through_date) -> RecognitionDelta | None:
    if unprocessed_units <= 0:
        return None
    if o.price_per_unit_cents is None or o.price_per_unit_cents <= 0:
        raise ValueError("consumption_payg obligation requires positive price_per_unit_cents")
    amount = unprocessed_units * o.price_per_unit_cents
    if amount <= 0:
        return None
    return RecognitionDelta(recognized_cents=amount, recognized_through=run_through_date)
```

Differences from `_compute_consumption` (1.5a): no `total_amount_cents` cap (no commitment), no `already_cents` short-circuit, math is direct multiplication.

### Recognition engine

`engine.py` reuses `_pending_usage_for` unchanged. The PAYG branch follows the same flow as `consumption` (load pending events, compute delta, mark events picked up) but credits a different account:

- PAYG: DR `o.unbilled_ar_account_code` / CR `o.revenue_account_code`
- Prepaid consumption: DR `o.deferred_revenue_account_code` / CR `o.revenue_account_code` (unchanged)

Implementation: the loop's `lines_agg` accumulator builds `(account_code, side) → cents`. For PAYG obligations, the debit account picked is `o.unbilled_ar_account_code`. Mixed runs (ratable + consumption + consumption_payg in one batch) coalesce naturally because `lines_agg` is keyed by account code.

### Billing reclassification

Two paths, primary + admin fallback.

**Primary — Zuora `invoice.posted`:**
M1's posting engine currently does `mapper(event.payload)` to build JE lines, then `post_entry`. We add a post-processor `reclassify_payg_lines(session, payload, lines)` invoked between `from_zuora_invoice` (genesis) and `post_entry`:

1. Walk `payload["lineItems"]`. Each carries `ratePlanChargeId`.
2. For each line, look up `PerformanceObligation` by `external_ref == ratePlanChargeId`.
3. If the obligation's pattern is `consumption_payg`, rewrite that line's credit account from the revenue account to `obligation.unbilled_ar_account_code`. Insert a corresponding `PaygReclassification` row referencing `event.id` and the obligation.
4. Lines whose obligation matches a non-PAYG pattern, or doesn't match at all, are passed through unchanged.

If the invoice has no PAYG lines, the line list is identical to the pre-1.5b output — zero regression for M1/M2a-1 behavior.

**Admin fallback — `POST /revrec/obligations/{obligation_id}/bill`:**
Body: `{invoice_amount_cents: int, period_start: date, period_end: date, external_ref: str | None}`.
- Validates `obligation.pattern == 'consumption_payg'` (else 422).
- Posts JE: DR `1000-AR` / CR `obligation.unbilled_ar_account_code` for `invoice_amount_cents`.
- Inserts `PaygReclassification` row.
- Idempotent on `external_ref` if provided (skip duplicate).
- MVP does **not** reconcile the supplied amount against the obligation's accumulated unbilled balance. Caller is trusted; a residual in the unbilled account is left visible in the UI for human inspection.

### Ingestion

Existing endpoints widen the pattern check. No new endpoints.

- `POST /revrec/usage`: change validation from `if obligation.pattern != "consumption"` to `if obligation.pattern not in ("consumption", "consumption_payg")`.
- `from_zuora_usage` (in `revrec.usage_genesis`): same widening.

### Admin API extensions

`ObligationIn` (Pydantic model) gains:
- `price_per_unit_cents: int | None = None`
- `unbilled_ar_account_code: str = "1500-UNBILLED-AR"`

`create_obligation` validation:
- `pattern == 'consumption_payg'` requires `price_per_unit_cents > 0`; else 422.
- `pattern != 'consumption_payg'` and `price_per_unit_cents is not None` → 422.

### UI

**Contract detail (obligation card).** PAYG obligations show three stat tiles instead of the 1.5a progress bar:

- **Units consumed** — sum of `usage_events.units` for this obligation, formatted with `unit_label`.
- **Recognized (unbilled)** — current balance attributable to this obligation = `sum(recognition_events.recognized_cents) − sum(payg_reclassifications.amount_cents)` for `obligation_id`.
- **Recognized (billed)** — `sum(payg_reclassifications.amount_cents)` for `obligation_id`.

Plus the same recent-usage-events disclosure pattern from 1.5a. No commitment progress bar, no over-commitment warning.

**Usage page `/revrec/usage`.** Unchanged. Both pattern types flow through it.

**Waterfall.** PAYG obligations contribute zero to all buckets. The waterfall route filters them out of its iteration.

**Revrec index.** Adds a KPI tile: **Unbilled AR** = sum of unbilled-AR account balances across the ledger (one query against `journal_lines` filtered by `account.code IN (SELECT DISTINCT unbilled_ar_account_code FROM performance_obligations)`).

### Reconciliation

MVP: no automated break detection. Residual unbilled balances surface in the per-obligation contract detail. Human inspection only. Automated reconciliation between Zuora invoice totals and accumulated unbilled AR is deferred.

## Error handling

| Case | Behavior |
|------|----------|
| Create PAYG obligation without `price_per_unit_cents` | 422 |
| Create non-PAYG with `price_per_unit_cents` | 422 |
| POST `/revrec/usage` for PAYG obligation | accept (widens 1.5a check) |
| POST `/revrec/usage` with `units <= 0` | 422 (existing) |
| Zuora `invoice.posted` line matches PAYG obligation | rewrite line CR account; create `PaygReclassification` |
| Zuora `invoice.posted` line matches non-PAYG obligation | unchanged (normal CR Revenue) |
| Zuora `invoice.posted` line matches no obligation | unchanged (normal default mapping) |
| Admin bill endpoint, obligation not PAYG | 422 |
| Admin bill endpoint, duplicate `external_ref` | 200 (idempotent skip) |
| Recognition engine encounters PAYG obligation with `price_per_unit_cents IS NULL` | `ValueError` (CHECK constraint should make this unreachable) |

## Testing strategy

~19 new tests across layers:

- **Unit `compute.py`** (5): zero units → None; happy path; missing-price raises; multi-run accumulation; dispatch routing.
- **Unit `waterfall.py`** (1): PAYG contributes zero.
- **Integration engine** (3): PAYG obligation + pending usage → correct JE + events marked; mixed-pattern run; zero-pending no-op.
- **Integration invoice reclassification** (4): PAYG line rewritten; non-PAYG line untouched; mixed invoice multi-credit; admin endpoint happy + 422.
- **Integration API** (4): PAYG create happy; missing price → 422; non-PAYG with price → 422; POST `/usage` to PAYG happy.
- **UI smoke** (1): contract detail renders PAYG with three stat tiles.
- **Property** (1): for random (price, event-list) pairs, trial balance zero AND `recognized_cents == sum(units) × price`.

Test data uses dates ≤ today (2026-04-24) to avoid the 5-minute future-skew validator on `occurred_at`.

## Migrations summary

- `0016_revrec_obligation_payg_fields.py` — adds `price_per_unit_cents`, `unbilled_ar_account_code`, extends pattern CHECK, adds PAYG-price CHECK, relaxes consumption-units CHECK.
- `0017_revrec_payg_reclassifications.py` — creates the new tracking table.

## Open questions / non-decisions

- Pattern name `consumption_payg` is the working choice. `usage_postpaid` was an alternative; settled on `consumption_payg` for consistency with the existing `consumption` family naming.
- `total_amount_cents` is nullable for PAYG (not 0). The CHECK constraint enforces.

## Self-review

- **Placeholders:** none. Every section has concrete code/SQL/HTTP shapes.
- **Internal consistency:** dispatch logic in compute, engine, reclassification post-processor, and admin endpoint all reference the same pattern string `'consumption_payg'` and the same column name `price_per_unit_cents`. `unbilled_ar_account_code` is consistently per-obligation.
- **Scope check:** single implementation plan reasonable — ~3 migrations, ~5 file edits, ~19 tests. Smaller than 1.5a (which had 22 plan tasks); estimate ~12-15 tasks.
- **Ambiguity:** `Recognized (unbilled)` per obligation is computed from `recognition_events − payg_reclassifications`, both keyed by `obligation_id`. Spec says this explicitly under UI / Contract detail.
