# M2a-1.5b — Pay-As-You-Go Recognition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `consumption_payg` recognition pattern: revenue accrues to Unbilled AR per usage event at a flat per-unit rate, then reclassifies to billed AR when Zuora invoices the consumed usage (or admin posts a bill).

**Architecture:** Sibling pattern to M2a-1.5a's `consumption`. Extends `performance_obligations` with `price_per_unit_cents` and `unbilled_ar_account_code`. New `payg_reclassifications` table tracks per-obligation billed amounts. Zuora `invoice.posted` post-processor rewrites line CR accounts for PAYG-matching obligations.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async (asyncpg writes, sync psycopg UI reads), Alembic, pytest + Hypothesis, Postgres 16.

---

## File Structure

**New files:**
- `core/alembic/versions/0016_revrec_obligation_payg_fields.py`
- `core/alembic/versions/0017_revrec_payg_reclassifications.py`
- `core/src/finledger/revrec/payg_billing.py` — line-rewrite helper + admin bill helper
- `core/tests/integration/test_revrec_payg.py` — PAYG engine + recognition flow
- `core/tests/integration/test_revrec_payg_billing.py` — invoice reclassification + admin endpoint
- `core/tests/property/test_revrec_payg_invariants.py`

**Modified:**
- `core/src/finledger/models/revrec.py` — fields + new `PaygReclassification` model
- `core/src/finledger/ledger/accounts.py` — seed `1500-UNBILLED-AR`
- `core/src/finledger/revrec/compute.py` — dispatch + `_compute_consumption_payg`
- `core/src/finledger/revrec/engine.py` — PAYG debit account branch
- `core/src/finledger/revrec/waterfall.py` — skip PAYG in route iteration
- `core/src/finledger/posting/engine.py` — invoke `reclassify_payg_lines` post-genesis
- `core/src/finledger/ui/routes/revrec.py` — admin API + admin /bill + contract_detail PAYG view + index KPI
- `core/src/finledger/ui/templates/revrec_contract_detail.html` — PAYG stat tiles
- `core/tests/integration/conftest.py` — TRUNCATE adds `payg_reclassifications`
- `core/tests/unit/test_revrec_compute.py` — PAYG cases
- `core/tests/unit/test_revrec_waterfall.py` — PAYG zero
- `core/tests/integration/test_revrec_api.py` — PAYG admin tests
- `core/tests/integration/test_ui_smoke.py` — PAYG render
- `README.md` — 1.5b section

---

## Batch A — Data model + accounts

### Task 1: Migration 0016 — PAYG fields on performance_obligations

**File:** `core/alembic/versions/0016_revrec_obligation_payg_fields.py`

```python
"""revrec: PAYG fields on performance_obligations

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "performance_obligations",
        sa.Column("price_per_unit_cents", sa.Integer(), nullable=True),
        schema="revrec",
    )
    op.add_column(
        "performance_obligations",
        sa.Column(
            "unbilled_ar_account_code", sa.Text(),
            nullable=False, server_default="1500-UNBILLED-AR",
        ),
        schema="revrec",
    )
    # Extend pattern CHECK
    op.execute(
        "ALTER TABLE revrec.performance_obligations "
        "DROP CONSTRAINT IF EXISTS ck_perf_obligations_pattern"
    )
    op.execute(
        "ALTER TABLE revrec.performance_obligations "
        "ADD CONSTRAINT ck_perf_obligations_pattern "
        "CHECK (pattern IN ('ratable_daily', 'point_in_time', 'consumption', 'consumption_payg'))"
    )
    # PAYG requires positive price
    op.execute(
        "ALTER TABLE revrec.performance_obligations "
        "ADD CONSTRAINT ck_perf_obligations_payg_price "
        "CHECK (pattern <> 'consumption_payg' "
        "OR (price_per_unit_cents IS NOT NULL AND price_per_unit_cents > 0))"
    )
    # Relax consumption-units CHECK to apply only to prepaid 'consumption'
    op.execute(
        "ALTER TABLE revrec.performance_obligations "
        "DROP CONSTRAINT IF EXISTS ck_perf_obligations_consumption_units"
    )
    op.execute(
        "ALTER TABLE revrec.performance_obligations "
        "ADD CONSTRAINT ck_perf_obligations_consumption_units "
        "CHECK (pattern <> 'consumption' "
        "OR (units_total IS NOT NULL AND units_total > 0))"
    )
    # Allow nullable total_amount_cents for PAYG
    op.alter_column(
        "performance_obligations", "total_amount_cents",
        existing_type=sa.BigInteger(), nullable=True, schema="revrec",
    )
    op.execute(
        "ALTER TABLE revrec.performance_obligations "
        "ADD CONSTRAINT ck_perf_obligations_amount_required "
        "CHECK (pattern = 'consumption_payg' OR total_amount_cents IS NOT NULL)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE revrec.performance_obligations DROP CONSTRAINT IF EXISTS ck_perf_obligations_amount_required")
    op.alter_column(
        "performance_obligations", "total_amount_cents",
        existing_type=sa.BigInteger(), nullable=False, schema="revrec",
    )
    op.execute("ALTER TABLE revrec.performance_obligations DROP CONSTRAINT IF EXISTS ck_perf_obligations_consumption_units")
    op.execute("ALTER TABLE revrec.performance_obligations DROP CONSTRAINT IF EXISTS ck_perf_obligations_payg_price")
    op.execute("ALTER TABLE revrec.performance_obligations DROP CONSTRAINT IF EXISTS ck_perf_obligations_pattern")
    op.execute(
        "ALTER TABLE revrec.performance_obligations "
        "ADD CONSTRAINT ck_perf_obligations_pattern "
        "CHECK (pattern IN ('ratable_daily', 'point_in_time', 'consumption'))"
    )
    op.drop_column("performance_obligations", "unbilled_ar_account_code", schema="revrec")
    op.drop_column("performance_obligations", "price_per_unit_cents", schema="revrec")
```

- [ ] Run: `.venv/Scripts/alembic upgrade head` from `core/`. Expect: `0016_revrec_obligation_payg_fields ... done`.
- [ ] Commit: `feat(revrec): performance_obligations PAYG columns + CHECKs`.

### Task 2: Migration 0017 — payg_reclassifications table

**File:** `core/alembic/versions/0017_revrec_payg_reclassifications.py`

```python
"""revrec: payg_reclassifications table

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payg_reclassifications",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("obligation_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("invoice_external_ref", sa.Text(), nullable=True),
        sa.Column("billed_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("journal_entry_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_event_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["obligation_id"], ["revrec.performance_obligations.id"]),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["ledger.journal_entries.id"]),
        sa.ForeignKeyConstraint(["source_event_id"], ["inbox.source_events.id"]),
        sa.CheckConstraint("amount_cents > 0", name="ck_payg_reclass_amount_positive"),
        schema="revrec",
    )
    op.create_index(
        "ix_payg_reclass_obligation",
        "payg_reclassifications",
        ["obligation_id"],
        schema="revrec",
    )


def downgrade() -> None:
    op.drop_index("ix_payg_reclass_obligation", table_name="payg_reclassifications", schema="revrec")
    op.drop_table("payg_reclassifications", schema="revrec")
```

- [ ] Run alembic upgrade. Commit: `feat(revrec): payg_reclassifications tracking table`.

### Task 3: Models — fields + PaygReclassification class

**File:** `core/src/finledger/models/revrec.py`

Add to `PerformanceObligation`:
```python
    price_per_unit_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unbilled_ar_account_code: Mapped[str] = mapped_column(Text, nullable=False, server_default="1500-UNBILLED-AR")
```

Make `total_amount_cents` nullable on the model:
```python
    total_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
```

Append new model class:
```python
class PaygReclassification(Base):
    __tablename__ = "payg_reclassifications"
    __table_args__ = {"schema": "revrec"}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    obligation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("revrec.performance_obligations.id"))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    invoice_external_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    billed_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ledger.journal_entries.id"))
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("inbox.source_events.id"), nullable=True)
```

- [ ] Commit: `feat(revrec): PerformanceObligation PAYG fields + PaygReclassification model`.

### Task 4: Seed `1500-UNBILLED-AR` in chart of accounts

**File:** `core/src/finledger/ledger/accounts.py`

Add a new entry to the seed list with code `"1500-UNBILLED-AR"`, name `"Unbilled Accounts Receivable / Contract Asset"`, type `asset`, normal `debit`. Match the existing seed entry shape exactly.

- [ ] Commit: `feat(ledger): seed 1500-UNBILLED-AR contract asset account`.

### Task 5: conftest — TRUNCATE adds payg_reclassifications

**File:** `core/tests/integration/conftest.py`

In the TRUNCATE statement, prepend `revrec.payg_reclassifications,` so it gets cleaned between tests.

- [ ] Commit: `test(conftest): truncate revrec.payg_reclassifications between tests`.

---

## Batch B — Compute branch

### Task 6: compute.py — PAYG dispatch + helper

**File:** `core/src/finledger/revrec/compute.py`

Extend `ObligationSnapshot`:
```python
    price_per_unit_cents: int | None = None
```

In `compute_recognition` add dispatch:
```python
    if obligation.pattern == "consumption_payg":
        return _compute_consumption_payg(obligation, unprocessed_units, run_through_date)
```

Add helper:
```python
def _compute_consumption_payg(
    o: ObligationSnapshot, unprocessed_units: int, run_through_date: date,
) -> RecognitionDelta | None:
    if unprocessed_units <= 0:
        return None
    if o.price_per_unit_cents is None or o.price_per_unit_cents <= 0:
        raise ValueError("consumption_payg obligation requires positive price_per_unit_cents")
    amount = unprocessed_units * o.price_per_unit_cents
    if amount <= 0:
        return None
    return RecognitionDelta(recognized_cents=amount, recognized_through=run_through_date)
```

### Task 7: compute unit tests (5)

**File:** `core/tests/unit/test_revrec_compute.py`

Append:
```python
def test_consumption_payg_zero_units_returns_none():
    snap = ObligationSnapshot(
        total_amount_cents=None, start_date=date(2026, 1, 1), end_date=None,
        pattern="consumption_payg", price_per_unit_cents=10,
    )
    assert compute_recognition(snap, 0, None, date(2026, 5, 1), unprocessed_units=0) is None


def test_consumption_payg_happy_path_units_times_price():
    snap = ObligationSnapshot(
        total_amount_cents=None, start_date=date(2026, 1, 1), end_date=None,
        pattern="consumption_payg", price_per_unit_cents=10,
    )
    delta = compute_recognition(snap, 0, None, date(2026, 5, 1), unprocessed_units=300)
    assert delta.recognized_cents == 3000


def test_consumption_payg_no_cap_above_arbitrary_amount():
    snap = ObligationSnapshot(
        total_amount_cents=None, start_date=date(2026, 1, 1), end_date=None,
        pattern="consumption_payg", price_per_unit_cents=5,
    )
    # Recognize on top of large already_recognized — no cap applies
    delta = compute_recognition(snap, 1_000_000, None, date(2026, 5, 1), unprocessed_units=10_000)
    assert delta.recognized_cents == 50_000


def test_consumption_payg_missing_price_raises():
    snap = ObligationSnapshot(
        total_amount_cents=None, start_date=date(2026, 1, 1), end_date=None,
        pattern="consumption_payg", price_per_unit_cents=None,
    )
    with pytest.raises(ValueError, match="price_per_unit_cents"):
        compute_recognition(snap, 0, None, date(2026, 5, 1), unprocessed_units=10)


def test_consumption_payg_zero_price_raises():
    snap = ObligationSnapshot(
        total_amount_cents=None, start_date=date(2026, 1, 1), end_date=None,
        pattern="consumption_payg", price_per_unit_cents=0,
    )
    with pytest.raises(ValueError, match="price_per_unit_cents"):
        compute_recognition(snap, 0, None, date(2026, 5, 1), unprocessed_units=10)
```

- [ ] Run: `.venv/Scripts/pytest tests/unit/test_revrec_compute.py -v`. All pass.
- [ ] Commit: `feat(revrec): compute_recognition consumption_payg branch`.

---

## Batch C — Engine extension

### Task 8: engine.py — PAYG debit account branch

**File:** `core/src/finledger/revrec/engine.py`

In `run_recognition`, change the line accumulation block. Currently:
```python
        lines_agg[(o.deferred_revenue_account_code, "debit")] += delta.recognized_cents
        lines_agg[(o.revenue_account_code, "credit")] += delta.recognized_cents
```
Replace with:
```python
        debit_account = (
            o.unbilled_ar_account_code
            if o.pattern == "consumption_payg"
            else o.deferred_revenue_account_code
        )
        lines_agg[(debit_account, "debit")] += delta.recognized_cents
        lines_agg[(o.revenue_account_code, "credit")] += delta.recognized_cents
```

Also extend the `_pending_usage_for` dispatch — currently it's gated by `if o.pattern == "consumption"`. Change to:
```python
        if o.pattern in ("consumption", "consumption_payg"):
            unprocessed_units, obl_event_ids = await _pending_usage_for(session, o.id)
```

And the snapshot construction needs to pass `price_per_unit_cents`:
```python
        snap = ObligationSnapshot(
            total_amount_cents=o.total_amount_cents or 0,
            start_date=o.start_date,
            end_date=o.end_date,
            pattern=o.pattern,
            units_total=o.units_total,
            price_per_unit_cents=o.price_per_unit_cents,
        )
```

The "even when delta is None for consumption, still mark events processed" branch already handles `consumption`. Update to:
```python
        if delta is None:
            if o.pattern in ("consumption", "consumption_payg") and obl_event_ids:
                picked_up_event_ids.extend(obl_event_ids)
            continue
```

And the success branch:
```python
        if o.pattern in ("consumption", "consumption_payg"):
            picked_up_event_ids.extend(obl_event_ids)
```

### Task 9: PAYG engine integration tests (3)

**File:** `core/tests/integration/test_revrec_payg.py`

```python
import uuid
from datetime import date, datetime, timezone
import pytest
from sqlalchemy import select
from finledger.models.ledger import JournalEntry, JournalLine, Account
from finledger.models.revrec import (
    Contract, PerformanceObligation, UsageEvent,
)
from finledger.revrec.engine import run_recognition


async def _seed_payg(session, *, price_per_unit_cents=100, contract_amount=None):
    contract = Contract(
        id=uuid.uuid4(),
        external_ref=f"C-{uuid.uuid4().hex[:8]}",
        effective_date=date(2026, 1, 1),
        status="active",
        total_amount_cents=contract_amount or 0,
        currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    session.add(contract)
    await session.flush()
    o = PerformanceObligation(
        id=uuid.uuid4(),
        contract_id=contract.id,
        description="PAYG test",
        pattern="consumption_payg",
        start_date=date(2026, 1, 1),
        end_date=None,
        total_amount_cents=None,
        currency="USD",
        price_per_unit_cents=price_per_unit_cents,
        unit_label="API calls",
        deferred_revenue_account_code="2000-DEFERRED-REV",
        revenue_account_code="4000-REV-SUB",
        unbilled_ar_account_code="1500-UNBILLED-AR",
        created_at=datetime.now(timezone.utc),
    )
    session.add(o)
    await session.flush()
    return contract, o


async def _insert_usage(session, *, obligation_id, units, key):
    ev = UsageEvent(
        id=uuid.uuid4(), obligation_id=obligation_id, units=units,
        occurred_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
        idempotency_key=key, source="api",
    )
    session.add(ev)
    await session.flush()
    return ev


@pytest.mark.asyncio
async def test_payg_recognition_debits_unbilled_ar(session):
    _, o = await _seed_payg(session, price_per_unit_cents=10)
    await _insert_usage(session, obligation_id=o.id, units=500, key="payg-1")
    await session.commit()

    run = await run_recognition(session, through_date=date(2026, 5, 1))
    await session.commit()

    assert run.total_recognized_cents == 5000
    lines = (await session.execute(
        select(JournalLine, Account.code).join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == run.journal_entry_id)
    )).all()
    by_code_side = {(code, line.side): line.amount_cents for line, code in lines}
    assert by_code_side[("1500-UNBILLED-AR", "debit")] == 5000
    assert by_code_side[("4000-REV-SUB", "credit")] == 5000

    ev = (await session.execute(select(UsageEvent))).scalar_one()
    assert ev.recognized_at is not None


@pytest.mark.asyncio
async def test_payg_no_pending_usage_no_op(session):
    _, _o = await _seed_payg(session)
    await session.commit()
    run = await run_recognition(session, through_date=date(2026, 5, 1))
    await session.commit()
    assert run.obligations_processed == 0
    assert run.total_recognized_cents == 0


@pytest.mark.asyncio
async def test_payg_mixed_with_consumption_and_ratable(session):
    # Three obligations across three patterns
    _, payg = await _seed_payg(session, price_per_unit_cents=10)
    await _insert_usage(session, obligation_id=payg.id, units=200, key="mix-payg")

    # Prepaid consumption obligation
    consumption_contract = Contract(
        id=uuid.uuid4(), external_ref=f"C-{uuid.uuid4().hex[:8]}",
        effective_date=date(2026, 1, 1), status="active",
        total_amount_cents=10000, currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    session.add(consumption_contract)
    await session.flush()
    cons_obl = PerformanceObligation(
        id=uuid.uuid4(), contract_id=consumption_contract.id,
        description="Prepaid consumption", pattern="consumption",
        start_date=date(2026, 1, 1), end_date=None,
        total_amount_cents=10000, currency="USD",
        units_total=1000, unit_label="calls",
        deferred_revenue_account_code="2000-DEFERRED-REV",
        revenue_account_code="4000-REV-SUB",
        created_at=datetime.now(timezone.utc),
    )
    session.add(cons_obl)
    await session.flush()
    await _insert_usage(session, obligation_id=cons_obl.id, units=200, key="mix-cons")

    # Ratable obligation
    rat_contract = Contract(
        id=uuid.uuid4(), external_ref=f"C-{uuid.uuid4().hex[:8]}",
        effective_date=date(2026, 5, 1), status="active",
        total_amount_cents=31000, currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    session.add(rat_contract)
    await session.flush()
    session.add(PerformanceObligation(
        id=uuid.uuid4(), contract_id=rat_contract.id,
        description="Ratable", pattern="ratable_daily",
        start_date=date(2026, 5, 1), end_date=date(2026, 5, 31),
        total_amount_cents=31000, currency="USD",
        deferred_revenue_account_code="2000-DEFERRED-REV",
        revenue_account_code="4000-REV-SUB",
        created_at=datetime.now(timezone.utc),
    ))
    await session.commit()

    run = await run_recognition(session, through_date=date(2026, 5, 10))
    await session.commit()

    assert run.obligations_processed == 3
    # PAYG: 200 * 10 = 2000
    # Prepaid consumption: 200/1000 * 10000 = 2000
    # Ratable: 10 days * 1000/day = 10000
    # Total: 14000
    assert run.total_recognized_cents == 14000

    lines = (await session.execute(
        select(JournalLine, Account.code).join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == run.journal_entry_id)
    )).all()
    by_code_side = {(code, line.side): line.amount_cents for line, code in lines}
    # Unbilled AR debit = 2000 (PAYG only)
    # Deferred Rev debit = 2000 + 10000 = 12000
    # Revenue credit = 14000
    assert by_code_side[("1500-UNBILLED-AR", "debit")] == 2000
    assert by_code_side[("2000-DEFERRED-REV", "debit")] == 12000
    assert by_code_side[("4000-REV-SUB", "credit")] == 14000
```

- [ ] Run: `.venv/Scripts/pytest tests/integration/test_revrec_payg.py -v`. All pass.
- [ ] Commit: `feat(revrec): engine PAYG branch debits unbilled AR`.

---

## Batch D — Admin API

### Task 10: ObligationIn extend + create_obligation validation

**File:** `core/src/finledger/ui/routes/revrec.py`

Extend `ObligationIn`:
```python
    price_per_unit_cents: int | None = None
    unbilled_ar_account_code: str = "1500-UNBILLED-AR"
```

In `create_obligation` add validations after the existing consumption check:
```python
    if body.pattern == "consumption_payg":
        if body.price_per_unit_cents is None or body.price_per_unit_cents <= 0:
            raise HTTPException(422, "consumption_payg obligation requires positive price_per_unit_cents")
        if body.units_total is not None:
            raise HTTPException(422, "consumption_payg does not use units_total")
    elif body.price_per_unit_cents is not None:
        raise HTTPException(422, "price_per_unit_cents only valid for consumption_payg pattern")
```

For PAYG, allow `total_amount_cents=None`. Update the `PerformanceObligation(...)` constructor to pass `price_per_unit_cents` and `unbilled_ar_account_code` from body.

### Task 11: POST /revrec/usage pattern widening

**File:** same. In the existing POST /usage handler, change pattern check from:
```python
    if obl.pattern != "consumption":
        raise HTTPException(422, "obligation pattern is not consumption")
```
to:
```python
    if obl.pattern not in ("consumption", "consumption_payg"):
        raise HTTPException(422, "obligation pattern is not consumption-based")
```

Also update `from_zuora_usage` in `core/src/finledger/revrec/usage_genesis.py` similarly:
```python
    if obligation.pattern not in ("consumption", "consumption_payg"):
```

### Task 12: PAYG admin API tests (4)

**File:** `core/tests/integration/test_revrec_api.py`

Append:
```python
@pytest.mark.asyncio
async def test_create_payg_obligation_happy(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "PAYG-API-1", "effective_date": "2026-05-01",
        "total_amount_cents": 0,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "PAYG API",
        "pattern": "consumption_payg",
        "start_date": "2026-05-01",
        "price_per_unit_cents": 5,
        "unit_label": "API calls",
    })
    assert r2.status_code == 201, r2.text


@pytest.mark.asyncio
async def test_create_payg_without_price_422(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "PAYG-API-2", "effective_date": "2026-05-01",
        "total_amount_cents": 0,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "no price", "pattern": "consumption_payg",
        "start_date": "2026-05-01",
    })
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_reject_price_on_non_payg_pattern_422(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "PAYG-API-3", "effective_date": "2026-05-01",
        "total_amount_cents": 1000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "ratable with price", "pattern": "ratable_daily",
        "start_date": "2026-05-01", "end_date": "2026-05-31",
        "total_amount_cents": 1000, "price_per_unit_cents": 5,
    })
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_post_usage_to_payg_obligation_succeeds(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "PAYG-USE", "effective_date": "2026-05-01",
        "total_amount_cents": 0,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "PAYG", "pattern": "consumption_payg",
        "start_date": "2026-05-01", "price_per_unit_cents": 10,
    })
    oid = r2.json()["id"]
    r3 = await async_client.post("/revrec/usage", json={
        "obligation_id": oid, "units": 100,
        "occurred_at": "2026-04-15T10:00:00Z",
        "idempotency_key": "payg-usage-1",
    })
    assert r3.status_code == 201, r3.text
```

- [ ] Run: `.venv/Scripts/pytest tests/integration/test_revrec_api.py -v`. All pass.
- [ ] Commit: `feat(revrec): admin API accepts consumption_payg pattern`.

---

## Batch E — Billing reclassification

### Task 13: payg_billing.py — line rewrite helper

**File:** `core/src/finledger/revrec/payg_billing.py`

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.ledger.post import LineSpec
from finledger.models.revrec import PerformanceObligation, PaygReclassification


async def reclassify_payg_lines(
    session: AsyncSession, payload: dict, lines: list[LineSpec], source_event_id: uuid.UUID,
) -> tuple[list[LineSpec], list[PaygReclassification]]:
    """For each invoice line whose ratePlanChargeId matches a PAYG obligation,
    rewrite the credit account from revenue to that obligation's unbilled_ar_account_code,
    and prepare a PaygReclassification record.

    Returns (rewritten_lines, pending_reclassifications). The reclassifications need to
    be inserted by the caller after the journal entry is posted (so journal_entry_id is known).
    """
    line_items = payload.get("lineItems") or []
    if not line_items:
        return lines, []

    rpc_ids = [li.get("ratePlanChargeId") for li in line_items if li.get("ratePlanChargeId")]
    if not rpc_ids:
        return lines, []

    obligations = (await session.execute(
        select(PerformanceObligation).where(PerformanceObligation.external_ref.in_(rpc_ids))
    )).scalars().all()
    payg_by_ref = {o.external_ref: o for o in obligations if o.pattern == "consumption_payg"}
    if not payg_by_ref:
        return lines, []

    rewritten: list[LineSpec] = []
    reclassifications: list[PaygReclassification] = []

    revenue_account_codes = {o.revenue_account_code for o in payg_by_ref.values()}

    # Build a per-line PAYG amount map: for each PAYG obligation, sum its line amounts
    payg_line_amounts: dict[str, int] = {}
    for li in line_items:
        rpc = li.get("ratePlanChargeId")
        if rpc and rpc in payg_by_ref:
            amt = int(li.get("amountCents", li.get("amount_cents", 0)))
            payg_line_amounts[rpc] = payg_line_amounts.get(rpc, 0) + amt

    total_payg_credit_to_rewrite = sum(payg_line_amounts.values())
    if total_payg_credit_to_rewrite <= 0:
        return lines, []

    # Rewrite: subtract the PAYG total from any credit line on a revenue account,
    # add an equivalent credit on the obligation's unbilled_ar_account_code.
    for line in lines:
        if line.side == "credit" and line.account_code in revenue_account_codes:
            rewritten_amount = line.amount_cents - total_payg_credit_to_rewrite
            if rewritten_amount > 0:
                rewritten.append(LineSpec(
                    account_code=line.account_code, side="credit",
                    amount_cents=rewritten_amount, currency=line.currency,
                ))
            # Add per-obligation Unbilled AR credits
            for rpc, amt in payg_line_amounts.items():
                obl = payg_by_ref[rpc]
                rewritten.append(LineSpec(
                    account_code=obl.unbilled_ar_account_code, side="credit",
                    amount_cents=amt, currency=line.currency,
                ))
        else:
            rewritten.append(line)

    # Prepare reclassification records (caller fills in journal_entry_id)
    for rpc, amt in payg_line_amounts.items():
        obl = payg_by_ref[rpc]
        reclassifications.append(PaygReclassification(
            id=uuid.uuid4(),
            obligation_id=obl.id,
            amount_cents=amt,
            invoice_external_ref=payload.get("externalId") or payload.get("invoiceNumber"),
            billed_at=datetime.now(timezone.utc),
            journal_entry_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),  # placeholder
            source_event_id=source_event_id,
        ))

    return rewritten, reclassifications
```

### Task 14: posting/engine.py — invoke reclassify after mapper

**File:** `core/src/finledger/posting/engine.py`

In `process_one`, after the existing genesis call (`from_zuora_invoice`) and **before** `post_entry`, call `reclassify_payg_lines`:

```python
        # PAYG reclassification: rewrite credit accounts on lines whose obligation is PAYG
        from finledger.revrec.payg_billing import reclassify_payg_lines
        if event.source == "zuora" and event.event_type == "invoice.posted":
            lines, payg_reclassifications = await reclassify_payg_lines(
                session, event.payload, lines, event.id,
            )
        else:
            payg_reclassifications = []
```

Then post the entry, capture the resulting JE id, and persist the reclassifications:

```python
        entry = await post_entry(
            session, lines=lines,
            memo=f"{event.source}:{event.event_type}:{event.external_id}",
            source_event_id=event.id,
        )
        for rec in payg_reclassifications:
            rec.journal_entry_id = entry.id
            session.add(rec)
```

This requires changing the existing `await post_entry(...)` call (which currently doesn't capture the returned entry) to assign and add reclassifications. Verify by reading the existing engine code first.

### Task 15: Admin /bill endpoint

**File:** `core/src/finledger/ui/routes/revrec.py`

Append:
```python
class BillIn(BaseModel):
    invoice_amount_cents: int
    period_start: date
    period_end: date
    external_ref: str | None = None


class BillOut(BaseModel):
    id: UUID
    journal_entry_id: UUID


@router.post("/obligations/{obligation_id}/bill", status_code=201, response_model=BillOut)
async def bill_payg_obligation(
    obligation_id: UUID, body: BillIn,
    session: AsyncSession = Depends(get_async_session),
):
    from finledger.models.revrec import PaygReclassification
    if body.invoice_amount_cents <= 0:
        raise HTTPException(422, "invoice_amount_cents must be positive")
    obl = (await session.execute(
        select(PerformanceObligation).where(PerformanceObligation.id == obligation_id)
    )).scalar_one_or_none()
    if obl is None:
        raise HTTPException(404, "obligation not found")
    if obl.pattern != "consumption_payg":
        raise HTTPException(422, "obligation is not consumption_payg")
    # Idempotency on external_ref
    if body.external_ref:
        existing = (await session.execute(
            select(PaygReclassification).where(
                PaygReclassification.invoice_external_ref == body.external_ref,
                PaygReclassification.obligation_id == obligation_id,
            )
        )).scalar_one_or_none()
        if existing is not None:
            return BillOut(id=existing.id, journal_entry_id=existing.journal_entry_id)
    from finledger.ledger.post import LineSpec, post_entry
    entry = await post_entry(
        session,
        lines=[
            LineSpec(account_code="1000-AR", side="debit",
                     amount_cents=body.invoice_amount_cents, currency=obl.currency),
            LineSpec(account_code=obl.unbilled_ar_account_code, side="credit",
                     amount_cents=body.invoice_amount_cents, currency=obl.currency),
        ],
        memo=f"payg-bill:{obligation_id}:{body.period_start.isoformat()}",
    )
    rec = PaygReclassification(
        id=uuid.uuid4(),
        obligation_id=obligation_id,
        amount_cents=body.invoice_amount_cents,
        invoice_external_ref=body.external_ref,
        billed_at=datetime.now(timezone.utc),
        journal_entry_id=entry.id,
    )
    session.add(rec)
    await session.commit()
    return BillOut(id=rec.id, journal_entry_id=entry.id)
```

### Task 16: Billing integration tests (4)

**File:** `core/tests/integration/test_revrec_payg_billing.py`

Tests:
1. Zuora `invoice.posted` with one PAYG line → DR AR / CR Unbilled AR + PaygReclassification row
2. Zuora `invoice.posted` with one regular line → DR AR / CR Revenue, no PaygReclassification
3. Zuora `invoice.posted` mixed PAYG + non-PAYG → multi-credit JE (Revenue + Unbilled AR)
4. Admin /bill happy path + 422 on non-PAYG obligation

Use the existing M1 zuora invoice payload shape with `lineItems[].ratePlanChargeId` and `amountCents` per line. Match by setting the obligation's `external_ref` to the `ratePlanChargeId`.

(Code omitted here for brevity — implement following the patterns from `test_revrec_consumption_zuora.py`.)

- [ ] Run: `.venv/Scripts/pytest tests/integration/test_revrec_payg_billing.py -v`. All pass.
- [ ] Commit: `feat(revrec): Zuora invoice.posted PAYG line reclassification + admin /bill`.

---

## Batch F — Waterfall + UI

### Task 17: Waterfall — PAYG zero contribution

**File:** `core/src/finledger/revrec/waterfall.py`

Add a branch at the top of `project_obligation_by_month`:
```python
    if pattern == "consumption_payg":
        return dict(out)
```

**File:** `core/tests/unit/test_revrec_waterfall.py`

```python
def test_consumption_payg_contributes_nothing():
    months = project_obligation_by_month(
        total_cents=0, start=date(2026, 1, 1), end=None,
        pattern="consumption_payg",
        already_cents=5000, already_through=None,
        today=date(2026, 5, 15), horizon_months=12,
    )
    assert sum(months.values()) == 0
```

### Task 18: Contract detail PAYG view + template tiles

**File:** `core/src/finledger/ui/routes/revrec.py`

In `contract_detail`, extend the obligation-views build for PAYG: add `recognized_unbilled` and `recognized_billed` fields, computed via:
- `recognized_unbilled = recognized_map.get(o.id, 0) − sum_of_payg_reclass_for_obligation`
- `recognized_billed = sum_of_payg_reclass_for_obligation`

Pull `payg_reclassifications` similarly to how `recognition_events` are pulled — group by obligation_id, sum amount_cents.

**File:** `core/src/finledger/ui/templates/revrec_contract_detail.html`

Inside the obligation card, add a `{% if o.pattern == "consumption_payg" %}` branch BEFORE the existing `{% if o.pattern == "consumption" %}` block. Render three tiles:
- Units consumed (`v.units_consumed` formatted with `o.unit_label`)
- Recognized (unbilled): `v.recognized_unbilled` formatted as currency
- Recognized (billed): `v.recognized_billed` formatted as currency

Use the same visual style as the existing recognized/deferred row.

### Task 19: UI smoke + revrec index Unbilled AR KPI

**File:** `core/tests/integration/test_ui_smoke.py`

Add:
```python
@pytest.mark.asyncio
async def test_revrec_payg_contract_renders(client_with_fresh_db):
    # Set up: create contract + PAYG obligation via direct DB insert through async session,
    # then GET /revrec/contracts/{id} and assert response includes "Recognized" wording.
    # Defer detailed setup to direct API calls if simpler.
    ...
```

(Implementor: simplest path is to make two API calls — POST contract + POST obligation with `consumption_payg` — then GET the detail page and assert key wording is present.)

**Revrec index KPI** (`/revrec`): in the index handler, compute `unbilled_ar_total = SELECT sum balance of accounts whose code IN (SELECT DISTINCT unbilled_ar_account_code FROM performance_obligations WHERE pattern='consumption_payg')`. Pass into the template; render as a tile alongside existing KPIs.

- [ ] Run: full UI smoke + waterfall tests. All pass.
- [ ] Commit: `feat(revrec): waterfall skips PAYG; contract detail shows PAYG tiles; index KPI`.

---

## Batch G — Property + docs + final

### Task 20: Property invariants

**File:** `core/tests/property/test_revrec_payg_invariants.py`

```python
import asyncio
import uuid
from datetime import date, datetime, timezone
from hypothesis import given, settings, HealthCheck, strategies as st
from sqlalchemy import func, select, text, case
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from finledger.ledger.accounts import seed_chart_of_accounts
from finledger.models.revrec import (
    Contract, PerformanceObligation, UsageEvent,
)
from finledger.models.ledger import JournalLine
from finledger.revrec.engine import run_recognition
from tests.integration.conftest import TEST_URL


@st.composite
def payg_setups(draw):
    price = draw(st.integers(min_value=1, max_value=1000))
    event_count = draw(st.integers(min_value=0, max_value=20))
    events = draw(st.lists(
        st.integers(min_value=1, max_value=10000),
        min_size=event_count, max_size=event_count,
    ))
    return (price, events)


async def _apply(setup):
    price, events = setup
    engine = create_async_engine(TEST_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "TRUNCATE revrec.payg_reclassifications, revrec.usage_events, "
                "revrec.recognition_events, revrec.recognition_runs, "
                "revrec.performance_obligations, revrec.contracts, "
                "gl.export_runs, recon.recon_breaks, recon.recon_runs, "
                "ledger.journal_lines, ledger.journal_entries, "
                "ledger.accounts, inbox.source_events RESTART IDENTITY CASCADE"
            ))
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionLocal() as s:
            await seed_chart_of_accounts(s)
            await s.commit()
        async with SessionLocal() as s:
            c = Contract(
                id=uuid.uuid4(), external_ref=f"P-{uuid.uuid4().hex[:8]}",
                effective_date=date(2026, 1, 1), status="active",
                total_amount_cents=0, currency="USD",
                created_at=datetime.now(timezone.utc),
            )
            s.add(c)
            await s.flush()
            o = PerformanceObligation(
                id=uuid.uuid4(), contract_id=c.id, description="x",
                pattern="consumption_payg",
                start_date=date(2026, 1, 1), end_date=None,
                total_amount_cents=None, currency="USD",
                price_per_unit_cents=price,
                deferred_revenue_account_code="2000-DEFERRED-REV",
                revenue_account_code="4000-REV-SUB",
                unbilled_ar_account_code="1500-UNBILLED-AR",
                created_at=datetime.now(timezone.utc),
            )
            s.add(o)
            for i, u in enumerate(events):
                s.add(UsageEvent(
                    id=uuid.uuid4(), obligation_id=o.id, units=u,
                    occurred_at=datetime.now(timezone.utc),
                    received_at=datetime.now(timezone.utc),
                    idempotency_key=f"prop-payg-{i}-{uuid.uuid4().hex[:6]}",
                    source="api",
                ))
            await s.commit()
        async with SessionLocal() as s:
            await run_recognition(s, through_date=date(2026, 6, 1))
            await s.commit()
        async with SessionLocal() as s:
            dr, cr = (await s.execute(
                select(
                    func.coalesce(func.sum(case((JournalLine.side == "debit", JournalLine.amount_cents), else_=0)), 0),
                    func.coalesce(func.sum(case((JournalLine.side == "credit", JournalLine.amount_cents), else_=0)), 0),
                )
            )).one()
            return int(dr), int(cr), price * sum(events)
    finally:
        await engine.dispose()


@given(setup=payg_setups())
@settings(max_examples=15, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_payg_trial_balance_zero(setup):
    dr, cr, _ = asyncio.run(_apply(setup))
    assert dr == cr


@given(setup=payg_setups())
@settings(max_examples=15, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_payg_recognized_equals_units_times_price(setup):
    dr, _cr, expected = asyncio.run(_apply(setup))
    assert dr == expected
```

### Task 21: README section

**File:** `README.md`

After the M2a-1.5a section, insert "What M2a-1.5b adds (pay-as-you-go)" with a short bullet list mirroring 1.5a's section style.

### Task 22: Final verification + lint + merge

- [ ] Full test sweep: `.venv/Scripts/pytest tests/`. Expect ~120 passed (101 baseline + ~19 new), 1 skipped, 1 xfailed.
- [ ] Lint: `.venv/Scripts/ruff check src tests`. Expect clean.
- [ ] Merge to master: `git checkout master && git merge --no-ff m2a1-5b -m "Merge ..."`.
- [ ] Tag: `git tag -a m2a1-5b -m "FinLedger M2a-1.5b — PAYG recognition shipped"`.
- [ ] Push: `git push origin master refs/tags/m2a1-5b refs/heads/m2a1-5b`.

---

## Self-Review

**Spec coverage:**
- Pattern + dispatch (Task 6, 7)
- Unbilled AR account, configurable per obligation (Task 1, 3, 8)
- payg_reclassifications table (Task 2, 3)
- POST /usage widening (Task 11)
- Admin API (Task 10, 12)
- Zuora invoice line rewrite (Task 13, 14)
- Admin /bill endpoint (Task 15)
- Billing tests (Task 16)
- Waterfall skip (Task 17)
- Contract detail tiles + KPI (Task 18, 19)
- Property invariants (Task 20)
- Docs + ship (Task 21, 22)

**Placeholder scan:** Task 16 and Task 19 say "code omitted for brevity" / "..." — flagged. Implementor should follow the patterns from `test_revrec_consumption_zuora.py` and existing UI smoke tests, but exact code is omitted because it's mechanical.

**Type consistency:** `consumption_payg` (string) used identically across tasks. `price_per_unit_cents` and `unbilled_ar_account_code` consistent in column / Pydantic / SQLAlchemy / engine references.
