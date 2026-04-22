# M2a-1.5a Committed Usage Drain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `consumption` recognition pattern that drains deferred revenue proportional to units consumed, with two ingestion paths (HTTP POST and Zuora webhook), batched daily recognition, and ledger-correct cap semantics.

**Architecture:** Two new migrations (0014 extends `revrec.performance_obligations` with `units_total` / `unit_label` / `external_ref`; 0015 creates `revrec.usage_events`). A new branch inside `compute_recognition`. An extension of `run_recognition` that picks up pending usage events before calling compute. A new `POST /usage` endpoint and a new non-posting handler path in the M1 posting engine for Zuora `usage.uploaded` webhooks. UI gets a new `/revrec/usage` page and a consumption section on the contract detail page.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0 (sync psycopg for UI reads, async asyncpg for writes/tests), FastAPI, Jinja2, HTMX, Alembic, Hypothesis, pytest, pytest-asyncio.

---

## File Structure

```
core/src/finledger/
  revrec/
    compute.py                    # EXTEND: add _compute_consumption + dispatch branch
    engine.py                     # EXTEND: pickup pending usage_events, mark recognized
    usage_genesis.py              # NEW: from_zuora_usage handler
    waterfall.py                  # EXTEND: consumption obligation projection branch
  models/
    revrec.py                     # EXTEND: new cols on PerformanceObligation, new UsageEvent
  posting/
    engine.py                     # EXTEND: NON_POSTING_HANDLERS dispatch
  ui/routes/
    revrec.py                     # EXTEND: accept pattern='consumption', POST /usage, GET /usage,
                                  #         contract detail consumption view
  ui/templates/
    revrec_contract_detail.html   # EXTEND: consumption progress + events mini-table
    revrec_usage.html             # NEW: usage events page
    base.html                     # EXTEND: add Usage sub-link under Revenue
core/alembic/versions/
  0014_revrec_obligation_consumption_fields.py   # NEW
  0015_revrec_usage_events.py                    # NEW
core/tests/
  unit/test_revrec_compute.py                          # EXTEND
  integration/test_revrec_consumption.py               # NEW
  integration/test_revrec_consumption_zuora.py         # NEW
  integration/test_revrec_api.py                       # EXTEND (POST /usage)
  integration/test_ui_smoke.py                         # EXTEND
  property/test_revrec_consumption_invariants.py       # NEW
```

Modified M1 files:
- `core/tests/integration/conftest.py` — truncate `revrec.usage_events` between tests
- `core/seed_revrec_demo.py` — seed one consumption obligation with a handful of usage events
- `README.md` — add M2a-1.5a section

---

## Task 1: Branch + scaffold

**Files:**
- None to create. Just branch setup.

- [ ] **Step 1.1: Create feature branch**

```bash
cd C:/Pratap/work/finledger
git checkout master
git pull origin master
git checkout -b m2a1-5a
```

- [ ] **Step 1.2: Verify clean state**

```bash
git status
cd core && .venv/Scripts/pytest tests/ -x 2>&1 | tail -3
```

Expected: working tree clean (besides `.claude/`, `.playwright-mcp/` untracked); full suite green (~72 passed, 1 skipped, 1 xfailed).

---

## Task 2: Migration 0014 — extend performance_obligations

**Files:**
- Create: `core/alembic/versions/0014_revrec_obligation_consumption_fields.py`

- [ ] **Step 2.1: Create migration**

```python
"""revrec obligation: units_total, unit_label, external_ref + CHECK updates

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "performance_obligations",
        sa.Column("units_total", sa.BigInteger, nullable=True),
        schema="revrec",
    )
    op.add_column(
        "performance_obligations",
        sa.Column("unit_label", sa.Text, nullable=True),
        schema="revrec",
    )
    op.add_column(
        "performance_obligations",
        sa.Column("external_ref", sa.Text, nullable=True),
        schema="revrec",
    )
    op.create_unique_constraint(
        "uq_performance_obligations_external_ref",
        "performance_obligations",
        ["external_ref"],
        schema="revrec",
    )
    # Extend pattern CHECK to include 'consumption'
    op.drop_constraint(
        "ck_perf_obligations_pattern", "performance_obligations", schema="revrec"
    )
    op.create_check_constraint(
        "ck_perf_obligations_pattern",
        "performance_obligations",
        "pattern IN ('ratable_daily', 'point_in_time', 'consumption')",
        schema="revrec",
    )
    # Consumption obligations require units_total
    op.create_check_constraint(
        "ck_perf_obligations_consumption_units",
        "performance_obligations",
        "pattern <> 'consumption' OR units_total IS NOT NULL",
        schema="revrec",
    )
    # Extend period CHECK: consumption may also have null end_date
    op.drop_constraint(
        "ck_perf_obligations_period", "performance_obligations", schema="revrec"
    )
    op.create_check_constraint(
        "ck_perf_obligations_period",
        "performance_obligations",
        "pattern IN ('point_in_time', 'consumption') OR "
        "(end_date IS NOT NULL AND end_date >= start_date)",
        schema="revrec",
    )


def downgrade() -> None:
    op.drop_constraint("ck_perf_obligations_period", "performance_obligations", schema="revrec")
    op.create_check_constraint(
        "ck_perf_obligations_period",
        "performance_obligations",
        "pattern = 'point_in_time' OR (end_date IS NOT NULL AND end_date >= start_date)",
        schema="revrec",
    )
    op.drop_constraint("ck_perf_obligations_consumption_units", "performance_obligations", schema="revrec")
    op.drop_constraint("ck_perf_obligations_pattern", "performance_obligations", schema="revrec")
    op.create_check_constraint(
        "ck_perf_obligations_pattern",
        "performance_obligations",
        "pattern IN ('ratable_daily', 'point_in_time')",
        schema="revrec",
    )
    op.drop_constraint("uq_performance_obligations_external_ref", "performance_obligations", schema="revrec")
    op.drop_column("performance_obligations", "external_ref", schema="revrec")
    op.drop_column("performance_obligations", "unit_label", schema="revrec")
    op.drop_column("performance_obligations", "units_total", schema="revrec")
```

- [ ] **Step 2.2: Apply and verify**

```bash
cd core && .venv/Scripts/alembic upgrade head
```

Expected: `Running upgrade 0013 -> 0014`.

- [ ] **Step 2.3: Commit**

```bash
git add core/alembic/versions/0014_revrec_obligation_consumption_fields.py
git commit -m "feat(revrec): extend performance_obligations for consumption pattern"
```

---

## Task 3: Migration 0015 — usage_events table

**Files:**
- Create: `core/alembic/versions/0015_revrec_usage_events.py`

- [ ] **Step 3.1: Create migration**

```python
"""revrec usage_events

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("obligation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("revrec.performance_obligations.id", ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("units", sa.BigInteger, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("inbox.source_events.id"), nullable=True),
        sa.Column("recognized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recognition_run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("revrec.recognition_runs.id"), nullable=True),
        sa.CheckConstraint("units > 0", name="ck_usage_events_units_positive"),
        sa.CheckConstraint("source IN ('api', 'zuora')", name="ck_usage_events_source"),
        schema="revrec",
    )
    op.create_index(
        "ix_usage_events_obligation", "usage_events", ["obligation_id"], schema="revrec"
    )
    op.create_index(
        "ix_usage_events_pending",
        "usage_events", ["obligation_id"],
        schema="revrec",
        postgresql_where=sa.text("recognized_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_usage_events_pending", table_name="usage_events", schema="revrec")
    op.drop_index("ix_usage_events_obligation", table_name="usage_events", schema="revrec")
    op.drop_table("usage_events", schema="revrec")
```

- [ ] **Step 3.2: Apply + commit**

```bash
cd core && .venv/Scripts/alembic upgrade head
git add core/alembic/versions/0015_revrec_usage_events.py
git commit -m "feat(revrec): usage_events table with pending partial index"
```

Expected: `Running upgrade 0014 -> 0015`.

---

## Task 4: SQLAlchemy models

**Files:**
- Modify: `core/src/finledger/models/revrec.py`

- [ ] **Step 4.1: Add new columns to `PerformanceObligation`**

Open `core/src/finledger/models/revrec.py`. Inside the `PerformanceObligation` class, after the existing `revenue_account_code` column and before `created_at`, add:

```python
    units_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    unit_label: Mapped[str | None] = mapped_column(String, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
```

- [ ] **Step 4.2: Add `UsageEvent` model**

Append to the same file:

```python
class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = ({"schema": "revrec"},)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    obligation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("revrec.performance_obligations.id"), nullable=False
    )
    units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_event_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("inbox.source_events.id"), nullable=True
    )
    recognized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recognition_run_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("revrec.recognition_runs.id"), nullable=True
    )
```

- [ ] **Step 4.3: Commit**

```bash
git add core/src/finledger/models/revrec.py
git commit -m "feat(revrec): UsageEvent model + consumption columns on PerformanceObligation"
```

---

## Task 5: Conftest update

**Files:**
- Modify: `core/tests/integration/conftest.py`

- [ ] **Step 5.1: Prepend usage_events to TRUNCATE list**

Edit the `clean_tables` fixture. Replace the TRUNCATE text so it includes `revrec.usage_events` as the first table (most-dependent):

```python
        await conn.execute(text(
            "TRUNCATE revrec.usage_events, revrec.recognition_events, "
            "revrec.recognition_runs, revrec.performance_obligations, "
            "revrec.contracts, gl.export_runs, recon.recon_breaks, "
            "recon.recon_runs, ledger.journal_lines, ledger.journal_entries, "
            "ledger.accounts, inbox.source_events RESTART IDENTITY CASCADE"
        ))
```

- [ ] **Step 5.2: Run full suite to confirm no regression**

```bash
cd core && .venv/Scripts/pytest tests/ -x 2>&1 | tail -3
```

Expected: same count as before the batch (72 passed, 1 skipped, 1 xfailed).

- [ ] **Step 5.3: Commit**

```bash
git add core/tests/integration/conftest.py
git commit -m "test(conftest): truncate revrec.usage_events between tests"
```

---

## Task 6: Compute — consumption branch (TDD)

**Files:**
- Modify: `core/src/finledger/revrec/compute.py`
- Modify: `core/tests/unit/test_revrec_compute.py`

- [ ] **Step 6.1: Write failing tests**

Append to `core/tests/unit/test_revrec_compute.py`:

```python
def snap_consumption(total, units_total):
    return ObligationSnapshot(
        total_amount_cents=total,
        start_date=date(2026, 1, 1),
        end_date=None,
        pattern="consumption",
        units_total=units_total,
    )


def test_consumption_zero_unprocessed_units_returns_none():
    s = snap_consumption(total=100000, units_total=1000)
    assert compute_recognition(s, 0, None, date(2026, 5, 1), unprocessed_units=0) is None


def test_consumption_partial_drain():
    # $100 for 1000 units = $0.10/unit.  300 units consumed → $30
    s = snap_consumption(total=10000, units_total=1000)
    d = compute_recognition(s, 0, None, date(2026, 5, 1), unprocessed_units=300)
    assert d is not None
    assert d.recognized_cents == 3000
    assert d.recognized_through == date(2026, 5, 1)


def test_consumption_full_drain_at_cap():
    s = snap_consumption(total=10000, units_total=1000)
    d = compute_recognition(s, 0, None, date(2026, 5, 1), unprocessed_units=1000)
    assert d.recognized_cents == 10000


def test_consumption_over_cap_is_capped():
    # 1500 units against 1000 units_total = 150% but only $10k committed
    s = snap_consumption(total=10000, units_total=1000)
    d = compute_recognition(s, 0, None, date(2026, 5, 1), unprocessed_units=1500)
    assert d.recognized_cents == 10000  # capped


def test_consumption_already_fully_recognized_returns_none():
    s = snap_consumption(total=10000, units_total=1000)
    assert compute_recognition(s, 10000, None, date(2026, 5, 1), unprocessed_units=500) is None


def test_consumption_partial_then_more_events_cap_at_remaining():
    # 600 units already recognized ($6000), then 600 more units arrive
    # Expected delta = min((600 * 10000) // 1000, 10000 - 6000) = min(6000, 4000) = 4000
    s = snap_consumption(total=10000, units_total=1000)
    d = compute_recognition(s, 6000, None, date(2026, 5, 1), unprocessed_units=600)
    assert d.recognized_cents == 4000


def test_consumption_rounding_floor():
    # 333 units / 1000 units_total * $100.00 = $33.30 → floor = 3330 cents
    s = snap_consumption(total=10000, units_total=1000)
    d = compute_recognition(s, 0, None, date(2026, 5, 1), unprocessed_units=333)
    assert d.recognized_cents == 3330
```

- [ ] **Step 6.2: Run, confirm failures**

```bash
cd core && .venv/Scripts/pytest tests/unit/test_revrec_compute.py -v
```

Expected: existing tests still pass; new tests either error (`ObligationSnapshot got unexpected keyword argument 'units_total'`) or fail on the `unprocessed_units` keyword. TDD red.

- [ ] **Step 6.3: Update `ObligationSnapshot` + add consumption branch**

Open `core/src/finledger/revrec/compute.py`. Extend `ObligationSnapshot` with `units_total`:

```python
@dataclass(frozen=True)
class ObligationSnapshot:
    """Minimum shape needed to compute recognition. Model-agnostic."""
    total_amount_cents: int
    start_date: date
    end_date: date | None
    pattern: str
    units_total: int | None = None
```

Extend `compute_recognition` signature and dispatch:

```python
def compute_recognition(
    obligation: ObligationSnapshot,
    already_recognized_cents: int,
    already_recognized_through: date | None,
    run_through_date: date,
    unprocessed_units: int = 0,
) -> RecognitionDelta | None:
    """Returns the amount to recognize between already_recognized_through (exclusive)
    and run_through_date (inclusive), or None if there's nothing to recognize."""
    if obligation.pattern == "point_in_time":
        return _compute_point_in_time(
            obligation, already_recognized_cents, run_through_date
        )
    if obligation.pattern == "ratable_daily":
        return _compute_ratable_daily(
            obligation, already_recognized_cents, already_recognized_through, run_through_date
        )
    if obligation.pattern == "consumption":
        return _compute_consumption(
            obligation, already_recognized_cents, unprocessed_units, run_through_date
        )
    raise ValueError(f"unknown pattern: {obligation.pattern}")
```

Add the new helper below the existing ones:

```python
def _compute_consumption(
    o: ObligationSnapshot,
    already_cents: int,
    unprocessed_units: int,
    run_through_date: date,
) -> RecognitionDelta | None:
    if unprocessed_units <= 0:
        return None
    if o.units_total is None or o.units_total <= 0:
        raise ValueError("consumption obligation requires positive units_total")
    if already_cents >= o.total_amount_cents:
        return None
    proposed = (unprocessed_units * o.total_amount_cents) // o.units_total
    remaining = o.total_amount_cents - already_cents
    amount = min(proposed, remaining)
    if amount <= 0:
        return None
    return RecognitionDelta(
        recognized_cents=amount,
        recognized_through=run_through_date,
    )
```

- [ ] **Step 6.4: Run, confirm green**

```bash
.venv/Scripts/pytest tests/unit/test_revrec_compute.py -v
```

Expected: all 14 pre-existing + 7 new = 21 passed.

- [ ] **Step 6.5: Commit**

```bash
git add core/src/finledger/revrec/compute.py core/tests/unit/test_revrec_compute.py
git commit -m "feat(revrec): compute_recognition consumption branch"
```

---

## Task 7: Engine — usage event pickup (first integration test + impl)

**Files:**
- Modify: `core/src/finledger/revrec/engine.py`
- Create: `core/tests/integration/test_revrec_consumption.py`

- [ ] **Step 7.1: Write failing test**

Create `core/tests/integration/test_revrec_consumption.py`:

```python
import uuid
from datetime import date, datetime, timezone
import pytest
from sqlalchemy import select, func
from finledger.models.ledger import JournalEntry, JournalLine, Account
from finledger.models.revrec import (
    Contract, PerformanceObligation, RecognitionEvent, UsageEvent,
)
from finledger.revrec.engine import run_recognition


async def _seed_consumption_obligation(session, *, total_cents, units_total, unit_label="API calls"):
    contract = Contract(
        id=uuid.uuid4(),
        external_ref=f"C-{uuid.uuid4().hex[:8]}",
        effective_date=date(2026, 1, 1),
        status="active",
        total_amount_cents=total_cents,
        currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    session.add(contract)
    await session.flush()
    obligation = PerformanceObligation(
        id=uuid.uuid4(),
        contract_id=contract.id,
        description="Consumption test",
        pattern="consumption",
        start_date=date(2026, 1, 1),
        end_date=None,
        total_amount_cents=total_cents,
        currency="USD",
        units_total=units_total,
        unit_label=unit_label,
        deferred_revenue_account_code="2000-DEFERRED-REV",
        revenue_account_code="4000-REV-SUB",
        created_at=datetime.now(timezone.utc),
    )
    session.add(obligation)
    await session.flush()
    return contract, obligation


async def _insert_usage(session, *, obligation_id, units, key, source="api"):
    ev = UsageEvent(
        id=uuid.uuid4(),
        obligation_id=obligation_id,
        units=units,
        occurred_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
        idempotency_key=key,
        source=source,
    )
    session.add(ev)
    await session.flush()
    return ev


@pytest.mark.asyncio
async def test_consumption_obligation_recognition_drains_correctly(session):
    _, obl = await _seed_consumption_obligation(
        session, total_cents=10000, units_total=1000,
    )
    await _insert_usage(session, obligation_id=obl.id, units=300, key="ev-1")
    await session.commit()

    run = await run_recognition(session, through_date=date(2026, 5, 1))
    await session.commit()

    assert run.obligations_processed == 1
    assert run.total_recognized_cents == 3000  # 300/1000 of $100

    entry = (await session.execute(
        select(JournalEntry).where(JournalEntry.id == run.journal_entry_id)
    )).scalar_one()
    lines = (await session.execute(
        select(JournalLine, Account.code)
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == entry.id)
    )).all()
    by_code_side = {(code, line.side): line.amount_cents for line, code in lines}
    assert by_code_side[("2000-DEFERRED-REV", "debit")] == 3000
    assert by_code_side[("4000-REV-SUB", "credit")] == 3000

    # Pending event should now be marked recognized
    picked = (await session.execute(
        select(UsageEvent).where(UsageEvent.obligation_id == obl.id)
    )).scalar_one()
    assert picked.recognized_at is not None
    assert picked.recognition_run_id == run.id
```

- [ ] **Step 7.2: Run, confirm fail**

```bash
cd core && .venv/Scripts/pytest tests/integration/test_revrec_consumption.py::test_consumption_obligation_recognition_drains_correctly -v
```

Expected: test fails because run_recognition doesn't pick up usage_events yet. Likely: `run.total_recognized_cents == 0`.

- [ ] **Step 7.3: Extend engine**

Open `core/src/finledger/revrec/engine.py`. Add a helper near `_obligation_state`:

```python
async def _pending_usage_for(
    session: AsyncSession, obligation_id: uuid.UUID
) -> tuple[int, list[uuid.UUID]]:
    """Return (sum of pending units, list of event ids) for an obligation."""
    rows = (await session.execute(
        select(UsageEvent.id, UsageEvent.units)
        .where(UsageEvent.obligation_id == obligation_id)
        .where(UsageEvent.recognized_at.is_(None))
    )).all()
    total_units = sum(int(units) for _id, units in rows)
    ids = [rid for rid, _ in rows]
    return total_units, ids
```

Add the import at the top of the file alongside the existing model imports:

```python
from finledger.models.revrec import (
    PerformanceObligation, RecognitionEvent, RecognitionRun, UsageEvent,
)
```

Inside the `run_recognition` function, update the loop over obligations to pick up usage events for consumption obligations. Find the existing loop body (the block that starts with `for o in obligations:`) and replace it with:

```python
    picked_up_event_ids: list[uuid.UUID] = []

    for o in obligations:
        already_cents, already_through = await _obligation_state(session, o.id)
        unprocessed_units = 0
        obl_event_ids: list[uuid.UUID] = []
        if o.pattern == "consumption":
            unprocessed_units, obl_event_ids = await _pending_usage_for(session, o.id)
        snap = ObligationSnapshot(
            total_amount_cents=o.total_amount_cents,
            start_date=o.start_date,
            end_date=o.end_date,
            pattern=o.pattern,
            units_total=o.units_total,
        )
        delta = compute_recognition(
            snap, already_cents, already_through, through_date,
            unprocessed_units=unprocessed_units,
        )
        if delta is None:
            # Even when compute returns None for consumption (e.g. fully recognized),
            # still mark pending events as processed so they're not re-queued forever.
            if o.pattern == "consumption" and obl_event_ids:
                picked_up_event_ids.extend(obl_event_ids)
            continue
        lines_agg[(o.deferred_revenue_account_code, "debit")] += delta.recognized_cents
        lines_agg[(o.revenue_account_code, "credit")] += delta.recognized_cents
        events.append(RecognitionEvent(
            id=uuid.uuid4(),
            run_id=run.id,
            obligation_id=o.id,
            recognized_cents=delta.recognized_cents,
            recognized_through=delta.recognized_through,
        ))
        obligations_processed += 1
        total += delta.recognized_cents
        if o.pattern == "consumption":
            picked_up_event_ids.extend(obl_event_ids)
```

After the existing `if obligations_processed > 0:` block (which posts the aggregated journal entry and adds RecognitionEvent rows), add the usage-event mark-recognized step. Find this existing code:

```python
    if obligations_processed > 0:
        lines = [ ... ]
        entry = await post_entry(...)
        run.journal_entry_id = entry.id
        for e in events:
            session.add(e)
```

Immediately after that block (still inside run_recognition, before the `run.obligations_processed = ...` counter update), insert:

```python
    if picked_up_event_ids:
        await session.execute(
            update(UsageEvent)
            .where(UsageEvent.id.in_(picked_up_event_ids))
            .values(recognized_at=datetime.now(timezone.utc), recognition_run_id=run.id)
        )
```

Also add `update` to the sqlalchemy import at the top of the file:

```python
from sqlalchemy import select, func, update
```

- [ ] **Step 7.4: Run, confirm pass**

```bash
.venv/Scripts/pytest tests/integration/test_revrec_consumption.py -v
```

Expected: 1 passed.

- [ ] **Step 7.5: Commit**

```bash
git add core/src/finledger/revrec/engine.py core/tests/integration/test_revrec_consumption.py
git commit -m "feat(revrec): engine picks up pending usage events + marks recognized"
```

---

## Task 8: Engine — over-cap and mixed-pattern tests

**Files:**
- Modify: `core/tests/integration/test_revrec_consumption.py`

- [ ] **Step 8.1: Append over-cap test**

```python
@pytest.mark.asyncio
async def test_consumption_over_cap_recognition_caps_at_commitment(session):
    _, obl = await _seed_consumption_obligation(
        session, total_cents=10000, units_total=1000,
    )
    # 1500 units (150% of commitment) in one event
    await _insert_usage(session, obligation_id=obl.id, units=1500, key="ev-over")
    await session.commit()

    run = await run_recognition(session, through_date=date(2026, 5, 1))
    await session.commit()

    # Recognition caps at $100 (total_amount_cents)
    assert run.total_recognized_cents == 10000

    # The event was still marked recognized (not left pending)
    ev = (await session.execute(select(UsageEvent))).scalar_one()
    assert ev.recognized_at is not None
    assert ev.recognition_run_id == run.id
```

- [ ] **Step 8.2: Append mixed-pattern test**

```python
@pytest.mark.asyncio
async def test_mixed_ratable_and_consumption_same_run(session):
    # One ratable obligation + one consumption obligation in separate contracts
    _, ratable_ob = await _seed_consumption_obligation(
        session, total_cents=10000, units_total=1000,
    )
    # Overwrite the consumption pattern on one of them → switch to ratable_daily
    ratable_ob.pattern = "ratable_daily"
    ratable_ob.start_date = date(2026, 5, 1)
    ratable_ob.end_date = date(2026, 5, 31)
    ratable_ob.units_total = None
    await session.flush()

    _, consumption_ob = await _seed_consumption_obligation(
        session, total_cents=20000, units_total=2000,
    )
    await _insert_usage(session, obligation_id=consumption_ob.id, units=500, key="ev-mix")
    await session.commit()

    run = await run_recognition(session, through_date=date(2026, 5, 10))
    await session.commit()

    # Ratable: 10 days of $10000/31 = floor(10000/31) * 10 = 322 * 10 = 3220
    # Consumption: 500/2000 of $200 = $50 = 5000
    assert run.obligations_processed == 2
    # Floor math means exact sum; tolerate a couple cents of floor for ratable
    assert 3000 <= run.total_recognized_cents - 5000 <= 3300
```

- [ ] **Step 8.3: Run + commit**

```bash
.venv/Scripts/pytest tests/integration/test_revrec_consumption.py -v
git add core/tests/integration/test_revrec_consumption.py
git commit -m "test(revrec): consumption over-cap + mixed-pattern runs"
```

Expected: 3 passed.

---

## Task 9: Admin API — accept consumption pattern

**Files:**
- Modify: `core/src/finledger/ui/routes/revrec.py`
- Modify: `core/tests/integration/test_revrec_api.py`

- [ ] **Step 9.1: Write failing tests**

Append to `core/tests/integration/test_revrec_api.py`:

```python
@pytest.mark.asyncio
async def test_create_consumption_obligation(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "CONSUMPTION-1", "effective_date": "2026-05-01",
        "total_amount_cents": 120000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "API calls",
        "pattern": "consumption",
        "start_date": "2026-05-01",
        "total_amount_cents": 120000,
        "units_total": 1000000,
        "unit_label": "API calls",
        "external_ref": "zuora-rpc-xyz",
    })
    assert r2.status_code == 201
    assert "id" in r2.json()


@pytest.mark.asyncio
async def test_create_consumption_obligation_without_units_total_422(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "CONSUMPTION-2", "effective_date": "2026-05-01",
        "total_amount_cents": 1000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "bad", "pattern": "consumption",
        "start_date": "2026-05-01", "total_amount_cents": 1000,
    })
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_reject_units_total_on_ratable_422(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "CONSUMPTION-3", "effective_date": "2026-05-01",
        "total_amount_cents": 1000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "bad", "pattern": "ratable_daily",
        "start_date": "2026-05-01", "end_date": "2026-05-31",
        "total_amount_cents": 1000,
        "units_total": 500,
    })
    assert r2.status_code == 422
```

- [ ] **Step 9.2: Extend ObligationIn + validation**

In `core/src/finledger/ui/routes/revrec.py`, find the `ObligationIn` class and extend:

```python
class ObligationIn(BaseModel):
    description: str
    pattern: str
    start_date: date
    end_date: date | None = None
    total_amount_cents: int
    currency: str = "USD"
    deferred_revenue_account_code: str = "2000-DEFERRED-REV"
    revenue_account_code: str = "4000-REV-SUB"
    units_total: int | None = None
    unit_label: str | None = None
    external_ref: str | None = None
```

Find `create_obligation` and extend validation. Replace the current validation block with:

```python
    if body.pattern == "ratable_daily" and body.end_date is None:
        raise HTTPException(422, "ratable_daily requires end_date")
    if body.pattern not in ("ratable_daily", "point_in_time", "consumption"):
        raise HTTPException(422, f"unknown pattern: {body.pattern}")
    if body.end_date is not None and body.end_date < body.start_date:
        raise HTTPException(422, "end_date before start_date")
    if body.pattern == "consumption":
        if body.units_total is None or body.units_total <= 0:
            raise HTTPException(422, "consumption pattern requires positive units_total")
    else:
        if body.units_total is not None:
            raise HTTPException(422, f"units_total only valid for consumption pattern, got {body.pattern}")
```

Also extend the `PerformanceObligation(...)` constructor call to pass the new fields:

```python
    obl = PerformanceObligation(
        id=uuid.uuid4(),
        contract_id=contract_id,
        description=body.description,
        pattern=body.pattern,
        start_date=body.start_date,
        end_date=body.end_date,
        total_amount_cents=body.total_amount_cents,
        currency=body.currency,
        deferred_revenue_account_code=body.deferred_revenue_account_code,
        revenue_account_code=body.revenue_account_code,
        units_total=body.units_total,
        unit_label=body.unit_label,
        external_ref=body.external_ref,
        created_at=datetime.now(timezone.utc),
    )
```

- [ ] **Step 9.3: Run + commit**

```bash
.venv/Scripts/pytest tests/integration/test_revrec_api.py -v -k "consumption or units_total"
git add core/src/finledger/ui/routes/revrec.py core/tests/integration/test_revrec_api.py
git commit -m "feat(revrec): admin API accepts consumption obligation pattern"
```

Expected: 3 new tests pass.

---

## Task 10: POST /usage endpoint (TDD)

**Files:**
- Modify: `core/src/finledger/ui/routes/revrec.py`
- Modify: `core/tests/integration/test_revrec_api.py`

- [ ] **Step 10.1: Write failing tests**

Append to `core/tests/integration/test_revrec_api.py`:

```python
@pytest.mark.asyncio
async def test_post_usage_event_success(async_client):
    # Seed contract + consumption obligation via admin API
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "USAGE-API-1", "effective_date": "2026-05-01",
        "total_amount_cents": 120000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "API calls",
        "pattern": "consumption",
        "start_date": "2026-05-01",
        "total_amount_cents": 120000,
        "units_total": 1000000,
    })
    oid = r2.json()["id"]

    r3 = await async_client.post("/usage", json={
        "obligation_id": oid,
        "units": 1500,
        "occurred_at": "2026-05-10T10:30:00Z",
        "idempotency_key": "app-evt-abc",
    })
    assert r3.status_code == 201, r3.text
    body = r3.json()
    assert "id" in body
    assert "received_at" in body


@pytest.mark.asyncio
async def test_post_usage_duplicate_idempotency_key_409(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "USAGE-API-2", "effective_date": "2026-05-01",
        "total_amount_cents": 1000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "x", "pattern": "consumption",
        "start_date": "2026-05-01", "total_amount_cents": 1000, "units_total": 100,
    })
    oid = r2.json()["id"]
    body = {
        "obligation_id": oid, "units": 1,
        "occurred_at": "2026-05-10T10:30:00Z",
        "idempotency_key": "dup-key-1",
    }
    r_a = await async_client.post("/usage", json=body)
    r_b = await async_client.post("/usage", json=body)
    assert r_a.status_code == 201
    assert r_b.status_code == 409


@pytest.mark.asyncio
async def test_post_usage_obligation_not_found_404(async_client):
    r = await async_client.post("/usage", json={
        "obligation_id": "00000000-0000-0000-0000-000000000000",
        "units": 1,
        "occurred_at": "2026-05-10T10:30:00Z",
        "idempotency_key": "nf-key",
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_usage_pattern_mismatch_422(async_client):
    # Ratable obligation
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "USAGE-API-MM", "effective_date": "2026-05-01",
        "total_amount_cents": 1000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "x", "pattern": "ratable_daily",
        "start_date": "2026-05-01", "end_date": "2026-05-31",
        "total_amount_cents": 1000,
    })
    oid = r2.json()["id"]
    r3 = await async_client.post("/usage", json={
        "obligation_id": oid,
        "units": 1,
        "occurred_at": "2026-05-10T10:30:00Z",
        "idempotency_key": "mm-key",
    })
    assert r3.status_code == 422


@pytest.mark.asyncio
async def test_post_usage_units_zero_422(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "USAGE-API-ZERO", "effective_date": "2026-05-01",
        "total_amount_cents": 1000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "x", "pattern": "consumption",
        "start_date": "2026-05-01", "total_amount_cents": 1000, "units_total": 100,
    })
    oid = r2.json()["id"]
    r3 = await async_client.post("/usage", json={
        "obligation_id": oid,
        "units": 0,
        "occurred_at": "2026-05-10T10:30:00Z",
        "idempotency_key": "zero-key",
    })
    assert r3.status_code == 422
```

- [ ] **Step 10.2: Implement endpoint**

Append to `core/src/finledger/ui/routes/revrec.py`:

```python
from datetime import timedelta
from sqlalchemy.exc import IntegrityError


class UsageIn(BaseModel):
    obligation_id: UUID
    units: int
    occurred_at: datetime
    idempotency_key: str


class UsageOut(BaseModel):
    id: UUID
    received_at: datetime


@router.post("/usage", status_code=201, response_model=UsageOut)
async def post_usage(
    body: UsageIn,
    session: AsyncSession = Depends(get_async_session),
):
    from finledger.models.revrec import UsageEvent
    if body.units <= 0:
        raise HTTPException(422, "units must be > 0")
    # Reject future-dated events beyond 5-min skew
    now = datetime.now(timezone.utc)
    if body.occurred_at.replace(tzinfo=timezone.utc) if body.occurred_at.tzinfo is None else body.occurred_at > now + timedelta(minutes=5):
        raise HTTPException(422, "occurred_at in the future")

    obligation = (await session.execute(
        select(PerformanceObligation).where(PerformanceObligation.id == body.obligation_id)
    )).scalar_one_or_none()
    if obligation is None:
        raise HTTPException(404, "obligation not found")
    if obligation.pattern != "consumption":
        raise HTTPException(422, f"obligation pattern is {obligation.pattern!r}, not 'consumption'")

    ev = UsageEvent(
        id=uuid.uuid4(),
        obligation_id=body.obligation_id,
        units=body.units,
        occurred_at=body.occurred_at,
        received_at=now,
        idempotency_key=body.idempotency_key,
        source="api",
    )
    session.add(ev)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        if "idempotency_key" in str(e.orig):
            raise HTTPException(409, "duplicate idempotency_key")
        raise
    return UsageOut(id=ev.id, received_at=ev.received_at)
```

- [ ] **Step 10.3: Run + commit**

```bash
.venv/Scripts/pytest tests/integration/test_revrec_api.py -v -k "usage"
git add core/src/finledger/ui/routes/revrec.py core/tests/integration/test_revrec_api.py
git commit -m "feat(revrec): POST /usage endpoint with validation + idempotency"
```

Expected: 5 new tests pass.

---

## Task 11: Zuora usage genesis + non-posting dispatch

**Files:**
- Create: `core/src/finledger/revrec/usage_genesis.py`
- Modify: `core/src/finledger/posting/engine.py`
- Create: `core/tests/integration/test_revrec_consumption_zuora.py`

- [ ] **Step 11.1: Write failing test**

Create `core/tests/integration/test_revrec_consumption_zuora.py`:

```python
import uuid
from datetime import date, datetime, timezone
import pytest
from sqlalchemy import select
from finledger.ingest.writer import insert_source_event
from finledger.models.revrec import (
    Contract, PerformanceObligation, UsageEvent,
)
from finledger.posting.engine import run_once as run_posting


async def _seed_consumption_obligation_with_external_ref(session, *, external_ref):
    contract = Contract(
        id=uuid.uuid4(), external_ref=f"C-{uuid.uuid4().hex[:8]}",
        effective_date=date(2026, 1, 1), status="active",
        total_amount_cents=10000, currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    session.add(contract)
    await session.flush()
    obligation = PerformanceObligation(
        id=uuid.uuid4(), contract_id=contract.id,
        description="Zuora usage test", pattern="consumption",
        start_date=date(2026, 1, 1), end_date=None,
        total_amount_cents=10000, currency="USD",
        units_total=1000, unit_label="calls",
        deferred_revenue_account_code="2000-DEFERRED-REV",
        revenue_account_code="4000-REV-SUB",
        external_ref=external_ref,
        created_at=datetime.now(timezone.utc),
    )
    session.add(obligation)
    await session.flush()
    return contract, obligation


@pytest.mark.asyncio
async def test_zuora_usage_webhook_matches_by_external_ref(session):
    _, obl = await _seed_consumption_obligation_with_external_ref(
        session, external_ref="rpc-abc123"
    )
    payload = {
        "eventType": "usage.uploaded",
        "ratePlanChargeId": "rpc-abc123",
        "quantity": 250,
        "startDateTime": "2026-05-10T00:00:00Z",
    }
    await insert_source_event(session, "zuora", "usage.uploaded", "zuora-evt-1", payload)
    await session.commit()

    posted = await run_posting(session)
    # usage.uploaded is a non-posting handler — no JE created
    assert posted == 0

    events = (await session.execute(
        select(UsageEvent).where(UsageEvent.obligation_id == obl.id)
    )).scalars().all()
    assert len(events) == 1
    assert events[0].units == 250
    assert events[0].source == "zuora"


@pytest.mark.asyncio
async def test_zuora_usage_webhook_unmatched_external_ref_skips_cleanly(session):
    await _seed_consumption_obligation_with_external_ref(
        session, external_ref="rpc-known"
    )
    payload = {
        "eventType": "usage.uploaded",
        "ratePlanChargeId": "rpc-unknown",
        "quantity": 100,
        "startDateTime": "2026-05-10T00:00:00Z",
    }
    await insert_source_event(session, "zuora", "usage.uploaded", "zuora-evt-2", payload)
    await session.commit()

    await run_posting(session)
    # No usage_events created
    events = (await session.execute(select(UsageEvent))).scalars().all()
    assert events == []


@pytest.mark.asyncio
async def test_zuora_usage_webhook_for_non_consumption_obligation_skips(session):
    contract = Contract(
        id=uuid.uuid4(), external_ref="C-RATABLE-Z",
        effective_date=date(2026, 1, 1), status="active",
        total_amount_cents=10000, currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    session.add(contract)
    await session.flush()
    ratable = PerformanceObligation(
        id=uuid.uuid4(), contract_id=contract.id,
        description="Ratable with external ref",
        pattern="ratable_daily",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        total_amount_cents=10000, currency="USD",
        deferred_revenue_account_code="2000-DEFERRED-REV",
        revenue_account_code="4000-REV-SUB",
        external_ref="rpc-ratable",
        created_at=datetime.now(timezone.utc),
    )
    session.add(ratable)
    await session.flush()
    payload = {
        "eventType": "usage.uploaded",
        "ratePlanChargeId": "rpc-ratable",
        "quantity": 5,
        "startDateTime": "2026-05-10T00:00:00Z",
    }
    await insert_source_event(session, "zuora", "usage.uploaded", "zuora-evt-3", payload)
    await session.commit()

    await run_posting(session)
    events = (await session.execute(select(UsageEvent))).scalars().all()
    assert events == []
```

- [ ] **Step 11.2: Implement `from_zuora_usage`**

Create `core/src/finledger/revrec/usage_genesis.py`:

```python
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.models.revrec import PerformanceObligation, UsageEvent

log = logging.getLogger(__name__)


def _parse_datetime(s: str) -> datetime:
    # Accept ISO-8601, including trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


async def from_zuora_usage(
    session: AsyncSession, payload: dict, source_event_id: uuid.UUID
) -> None:
    """Map a Zuora usage.uploaded webhook to a usage_events row.

    Skips (with INFO log) if required fields missing, obligation not found by
    external_ref, or obligation is not a consumption pattern.
    """
    rate_plan_charge_id = payload.get("ratePlanChargeId")
    quantity = payload.get("quantity")
    start_date = payload.get("startDateTime")
    if not (rate_plan_charge_id and quantity is not None and start_date):
        log.info("zuora usage event missing required fields; skipping")
        return
    try:
        units = int(quantity)
    except (TypeError, ValueError):
        log.info("zuora usage event has non-integer quantity; skipping")
        return
    if units <= 0:
        log.info("zuora usage event has non-positive quantity; skipping")
        return

    obligation = (await session.execute(
        select(PerformanceObligation).where(
            PerformanceObligation.external_ref == rate_plan_charge_id
        )
    )).scalar_one_or_none()
    if obligation is None:
        log.info(f"no obligation matches rate_plan_charge_id={rate_plan_charge_id!r}; skipping")
        return
    if obligation.pattern != "consumption":
        log.warning(
            f"zuora usage event for obligation with pattern {obligation.pattern!r}, "
            f"not 'consumption'; skipping"
        )
        return

    session.add(UsageEvent(
        id=uuid.uuid4(),
        obligation_id=obligation.id,
        units=units,
        occurred_at=_parse_datetime(start_date),
        received_at=datetime.now(timezone.utc),
        idempotency_key=f"zuora:{source_event_id}",
        source="zuora",
        source_event_id=source_event_id,
    ))
    await session.flush()
```

- [ ] **Step 11.3: Extend posting engine for non-posting dispatch**

Open `core/src/finledger/posting/engine.py`. Locate `process_one`. At the very top of the function (before `get_mapper` is called), insert the non-posting handler branch:

```python
async def process_one(session: AsyncSession, event: SourceEvent) -> bool:
    """Process a single source event. Returns True if a journal entry was posted."""
    # Non-posting handlers: source events that trigger side-effects (e.g., usage
    # event ingestion) but do NOT produce a journal entry of their own.
    from finledger.revrec.usage_genesis import from_zuora_usage
    NON_POSTING_HANDLERS = {
        ("zuora", "usage.uploaded"): from_zuora_usage,
    }
    key = (event.source, event.event_type)
    if key in NON_POSTING_HANDLERS:
        try:
            await NON_POSTING_HANDLERS[key](session, event.payload, event.id)
            event.processed_at = datetime.now(timezone.utc)
            event.processing_error = None
            await session.flush()
        except Exception as e:
            event.processing_error = f"{type(e).__name__}: {e}"
            await session.flush()
        return False  # no JE posted

    # ... existing mapper dispatch below unchanged ...
```

Leave the rest of `process_one` exactly as it is — the mapper dispatch and its genesis call for `invoice.posted` are untouched.

- [ ] **Step 11.4: Run + commit**

```bash
.venv/Scripts/pytest tests/integration/test_revrec_consumption_zuora.py -v
git add core/src/finledger/revrec/usage_genesis.py core/src/finledger/posting/engine.py core/tests/integration/test_revrec_consumption_zuora.py
git commit -m "feat(revrec): Zuora usage.uploaded webhook → usage_events"
```

Expected: 3 passed. M1 posting engine tests (`test_posting_engine.py`) must still pass — don't skip them.

- [ ] **Step 11.5: Regression check — M1 posting tests still green**

```bash
.venv/Scripts/pytest tests/integration/test_posting_engine.py tests/integration/test_revrec_genesis_e2e.py -v
```

Expected: all pass. No regressions from the dispatch change.

---

## Task 12: Full end-to-end Zuora consumption flow

**Files:**
- Modify: `core/tests/integration/test_revrec_consumption_zuora.py`

- [ ] **Step 12.1: Append end-to-end test**

```python
from datetime import date as _date
from finledger.revrec.engine import run_recognition


@pytest.mark.asyncio
async def test_zuora_usage_flows_through_to_recognition(session):
    _, obl = await _seed_consumption_obligation_with_external_ref(
        session, external_ref="rpc-e2e"
    )
    for i, qty in enumerate([100, 150, 250]):
        payload = {
            "eventType": "usage.uploaded",
            "ratePlanChargeId": "rpc-e2e",
            "quantity": qty,
            "startDateTime": "2026-05-10T00:00:00Z",
        }
        await insert_source_event(
            session, "zuora", "usage.uploaded", f"zuora-e2e-{i}", payload
        )
    await session.commit()
    await run_posting(session)

    # Three usage events accumulated, none recognized yet
    events = (await session.execute(select(UsageEvent))).scalars().all()
    assert len(events) == 3
    assert all(ev.recognized_at is None for ev in events)

    run = await run_recognition(session, through_date=_date(2026, 5, 20))
    await session.commit()

    # Total units = 500, commitment = 1000 units / $100 → 50% drain = $50
    assert run.total_recognized_cents == 5000
    events = (await session.execute(select(UsageEvent))).scalars().all()
    assert all(ev.recognized_at is not None for ev in events)
    assert all(ev.recognition_run_id == run.id for ev in events)
```

- [ ] **Step 12.2: Run + commit**

```bash
.venv/Scripts/pytest tests/integration/test_revrec_consumption_zuora.py -v
git add core/tests/integration/test_revrec_consumption_zuora.py
git commit -m "test(revrec): Zuora usage → usage_events → recognition end-to-end"
```

Expected: 4 passed total in that file.

---

## Task 13: GET /usage read endpoint

**Files:**
- Modify: `core/src/finledger/ui/routes/revrec.py`
- Modify: `core/tests/integration/test_revrec_api.py`

- [ ] **Step 13.1: Write failing tests**

Append to `test_revrec_api.py`:

```python
@pytest.mark.asyncio
async def test_list_usage_empty_json(async_client):
    r = await async_client.get("/usage", headers={"accept": "application/json"})
    assert r.status_code == 200
    assert r.json() == {"events": []}


@pytest.mark.asyncio
async def test_list_usage_returns_events_newest_first(async_client):
    r = await async_client.post("/revrec/contracts", json={
        "external_ref": "USAGE-LIST", "effective_date": "2026-05-01",
        "total_amount_cents": 1000,
    })
    cid = r.json()["id"]
    r2 = await async_client.post(f"/revrec/contracts/{cid}/obligations", json={
        "description": "x", "pattern": "consumption",
        "start_date": "2026-05-01", "total_amount_cents": 1000, "units_total": 1000,
    })
    oid = r2.json()["id"]
    for i in range(3):
        await async_client.post("/usage", json={
            "obligation_id": oid, "units": 10 * (i + 1),
            "occurred_at": f"2026-05-{10 + i}T10:00:00Z",
            "idempotency_key": f"list-key-{i}",
        })
    r3 = await async_client.get("/usage", headers={"accept": "application/json"})
    body = r3.json()
    assert len(body["events"]) == 3
    # Newest first by received_at
    units = [e["units"] for e in body["events"]]
    assert units == [30, 20, 10]
```

- [ ] **Step 13.2: Implement**

Add to `core/src/finledger/ui/routes/revrec.py`:

```python
@router.get("/usage")
async def list_usage(
    request: Request,
    obligation_id: UUID | None = None,
    session: AsyncSession = Depends(get_async_session),
):
    from finledger.models.revrec import UsageEvent
    q = select(UsageEvent).order_by(UsageEvent.received_at.desc()).limit(500)
    if obligation_id is not None:
        q = q.where(UsageEvent.obligation_id == obligation_id)
    rows = (await session.execute(q)).scalars().all()
    data = {
        "events": [
            {
                "id": str(e.id),
                "obligation_id": str(e.obligation_id),
                "units": e.units,
                "occurred_at": e.occurred_at.isoformat(),
                "received_at": e.received_at.isoformat(),
                "source": e.source,
                "recognized_at": e.recognized_at.isoformat() if e.recognized_at else None,
                "recognition_run_id": str(e.recognition_run_id) if e.recognition_run_id else None,
            }
            for e in rows
        ]
    }
    if _wants_json(request):
        return JSONResponse(data)
    return request.app.state.templates.TemplateResponse(
        request=request, name="revrec_usage.html",
        context={"events": rows},
    )
```

- [ ] **Step 13.3: Run + commit**

```bash
.venv/Scripts/pytest tests/integration/test_revrec_api.py -v -k "usage"
git add core/src/finledger/ui/routes/revrec.py core/tests/integration/test_revrec_api.py
git commit -m "feat(revrec): GET /usage list endpoint (JSON + HTML)"
```

Expected: 7 usage tests pass (5 POST from task 10 + 2 GET).

---

## Task 14: Waterfall consumption branch

**Files:**
- Modify: `core/src/finledger/revrec/waterfall.py`
- Modify: `core/tests/unit/test_revrec_waterfall.py`

- [ ] **Step 14.1: Add failing test**

Append to `core/tests/unit/test_revrec_waterfall.py`:

```python
def test_consumption_remaining_collapses_to_today_month():
    from finledger.revrec.waterfall import project_obligation_by_month
    # $1000 commitment, 60% already recognized → $400 remaining, all in current month
    months = project_obligation_by_month(
        total_cents=100000, start=date(2026, 1, 1), end=None,
        pattern="consumption",
        already_cents=60000, already_through=None,
        today=date(2026, 5, 15), horizon_months=12,
    )
    assert months[date(2026, 5, 1)] == 40000
    # No other buckets populated
    assert len([k for k, v in months.items() if v > 0]) == 1


def test_consumption_fully_recognized_returns_empty():
    from finledger.revrec.waterfall import project_obligation_by_month
    months = project_obligation_by_month(
        total_cents=100000, start=date(2026, 1, 1), end=None,
        pattern="consumption",
        already_cents=100000, already_through=None,
        today=date(2026, 5, 15), horizon_months=12,
    )
    assert sum(months.values()) == 0
```

- [ ] **Step 14.2: Implement**

Open `core/src/finledger/revrec/waterfall.py`. In `project_obligation_by_month`, add a branch for consumption immediately after the `point_in_time` branch:

```python
    if pattern == "consumption":
        if already_cents >= total_cents:
            return dict(out)
        remaining = total_cents - already_cents
        out[_month_start(today)] += remaining
        return dict(out)
```

- [ ] **Step 14.3: Run + commit**

```bash
.venv/Scripts/pytest tests/unit/test_revrec_waterfall.py -v
git add core/src/finledger/revrec/waterfall.py core/tests/unit/test_revrec_waterfall.py
git commit -m "feat(revrec): waterfall consumption branch — remaining in current month"
```

Expected: 6 tests pass (4 prior + 2 new).

- [ ] **Step 14.4: Update waterfall route to pass `units_total` through snapshot**

This was already covered — the waterfall route calls `project_obligation_by_month` with `pattern=o.pattern`. The new branch doesn't need `units_total` since the collapse uses `total_amount_cents - already_cents` directly. No route change needed. Verify by re-running the `/revrec/waterfall` JSON endpoint test:

```bash
.venv/Scripts/pytest tests/integration/test_revrec_api.py::test_waterfall_json_has_months_and_total -v
```

Expected: still passes.

---

## Task 15: Usage events page template

**Files:**
- Create: `core/src/finledger/ui/templates/revrec_usage.html`

- [ ] **Step 15.1: Create template**

```html
{% extends "base.html" %}
{% block title %}Usage Events{% endblock %}
{% set active = "revrec" %}
{% block content %}
<p><a href="/revrec" class="link">&larr; Revenue</a></p>
<h1>Usage Events</h1>
<p class="subtitle">Raw consumption events. Status "Pending" = queued for next recognition run.</p>

<div class="card" style="overflow-x: auto;">
{% if events %}
<table>
<thead>
  <tr>
    <th>Received</th>
    <th>Occurred</th>
    <th style="text-align: right;">Units</th>
    <th>Source</th>
    <th>Obligation</th>
    <th>Status</th>
  </tr>
</thead>
<tbody>
{% for e in events %}
<tr>
  <td class="mono">{{ e.received_at.strftime("%Y-%m-%d %H:%M:%S") }}</td>
  <td class="mono">{{ e.occurred_at.strftime("%Y-%m-%d %H:%M:%S") }}</td>
  <td class="mono" style="text-align: right;">{{ "{:,}".format(e.units) }}</td>
  <td>{{ e.source }}</td>
  <td class="mono">{{ e.obligation_id|string|truncate(8, True, '') }}&hellip;</td>
  <td>
    {% if e.recognized_at %}
      <span class="pill pill-ok">Recognized</span>
    {% else %}
      <span class="pill pill-pending">Pending</span>
    {% endif %}
  </td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<div class="empty">
  <div class="empty-icon">&#x1F4CA;</div>
  <div class="empty-title">No usage events yet</div>
  <div class="empty-hint">POST to <code>/usage</code> or send a Zuora <code>usage.uploaded</code> webhook.</div>
</div>
{% endif %}
</div>
{% endblock %}
```

- [ ] **Step 15.2: Commit**

```bash
git add core/src/finledger/ui/templates/revrec_usage.html
git commit -m "feat(ui): /revrec/usage events page template"
```

---

## Task 16: Contract detail consumption section

**Files:**
- Modify: `core/src/finledger/ui/routes/revrec.py`
- Modify: `core/src/finledger/ui/templates/revrec_contract_detail.html`

- [ ] **Step 16.1: Extend contract_detail handler**

Open `core/src/finledger/ui/routes/revrec.py`. Find the `contract_detail` function. After the existing `recognized_map` build, add consumption-specific data:

```python
    # Consumption obligation view extras: units consumed + recent events
    from finledger.models.revrec import UsageEvent
    consumption_ids = [o.id for o in obligations if o.pattern == "consumption"]
    units_by_obligation: dict = {}
    recent_events_by_obligation: dict = {}
    if consumption_ids:
        unit_rows = (await session.execute(
            select(
                UsageEvent.obligation_id,
                func.coalesce(func.sum(UsageEvent.units), 0),
            )
            .where(UsageEvent.obligation_id.in_(consumption_ids))
            .group_by(UsageEvent.obligation_id)
        )).all()
        units_by_obligation = {oid: int(n) for oid, n in unit_rows}
        for oid in consumption_ids:
            recent = (await session.execute(
                select(UsageEvent)
                .where(UsageEvent.obligation_id == oid)
                .order_by(UsageEvent.received_at.desc())
                .limit(5)
            )).scalars().all()
            recent_events_by_obligation[oid] = recent
```

Then in the `obl_views.append({...})` loop, add three new keys:

```python
    obl_views = []
    for o in obligations:
        recognized = recognized_map.get(o.id, 0)
        pct = int(100 * recognized / o.total_amount_cents) if o.total_amount_cents else 0
        units_consumed = units_by_obligation.get(o.id, 0)
        units_pct = (
            int(100 * units_consumed / o.units_total)
            if (o.pattern == "consumption" and o.units_total)
            else 0
        )
        obl_views.append({
            "obligation": o,
            "recognized": recognized,
            "deferred": o.total_amount_cents - recognized,
            "pct": pct,
            "units_consumed": units_consumed,
            "units_pct": units_pct,
            "recent_events": recent_events_by_obligation.get(o.id, []),
        })
```

- [ ] **Step 16.2: Extend template**

Open `core/src/finledger/ui/templates/revrec_contract_detail.html`. Find the existing obligation card loop. Inside the card, AFTER the existing `.obl-stats` div and before the closing card `</div>`, add the consumption section:

```html
    {% if o.pattern == "consumption" %}
      <div style="margin-top: 1rem; padding-top: 0.75rem; border-top: 1px solid var(--line);">
        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.4rem;">
          <div style="font-size: 0.82rem; color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600;">
            Consumption
          </div>
          <div style="font-size: 0.85rem; color: var(--ink-3);" class="mono">
            {{ "{:,}".format(v.units_consumed) }} / {{ "{:,}".format(o.units_total) }} {{ o.unit_label or "units" }}
          </div>
        </div>
        <div class="obl-bar">
          <div class="obl-bar-fill" style="width: {% if v.units_pct > 100 %}100{% else %}{{ v.units_pct }}{% endif %}%; {% if v.units_pct > 100 %}background: var(--err);{% endif %}"></div>
        </div>
        {% if v.units_pct > 100 %}
          <div style="font-size: 0.78rem; color: var(--err); margin-top: 0.35rem;">
            Over commitment by {{ v.units_pct - 100 }}% &mdash; overage flagging lands in M2a-1.5c.
          </div>
        {% endif %}
        {% if v.recent_events %}
          <details style="margin-top: 0.75rem;">
            <summary style="cursor: pointer; font-size: 0.82rem; color: var(--ink-3);">Recent usage events ({{ v.recent_events|length }})</summary>
            <table style="margin-top: 0.5rem; font-size: 0.82rem;">
              <thead><tr><th>Received</th><th style="text-align:right">Units</th><th>Source</th></tr></thead>
              <tbody>
                {% for ev in v.recent_events %}
                <tr>
                  <td class="mono">{{ ev.received_at.strftime("%Y-%m-%d %H:%M") }}</td>
                  <td class="mono" style="text-align:right">{{ "{:,}".format(ev.units) }}</td>
                  <td>{{ ev.source }}</td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
          </details>
        {% endif %}
      </div>
    {% endif %}
```

- [ ] **Step 16.3: Commit**

```bash
git add core/src/finledger/ui/routes/revrec.py core/src/finledger/ui/templates/revrec_contract_detail.html
git commit -m "feat(ui): contract detail shows consumption progress + recent events"
```

---

## Task 17: UI smoke tests for /revrec/usage

**Files:**
- Modify: `core/tests/integration/test_ui_smoke.py`

- [ ] **Step 17.1: Append smoke test**

Append:

```python
@pytest.mark.asyncio
async def test_revrec_usage_empty_returns_200(client_with_fresh_db):
    async with AsyncClient(
        transport=ASGITransport(app=client_with_fresh_db), base_url="http://test", follow_redirects=True
    ) as c:
        r = await c.get("/usage")
    assert r.status_code == 200
    assert "Usage Events" in r.text
```

- [ ] **Step 17.2: Run + commit**

```bash
.venv/Scripts/pytest tests/integration/test_ui_smoke.py -v
git add core/tests/integration/test_ui_smoke.py
git commit -m "test(ui): /revrec/usage smoke test"
```

Expected: all prior UI smoke tests plus the new one green.

---

## Task 18: Property-based invariants

**Files:**
- Create: `core/tests/property/test_revrec_consumption_invariants.py`

- [ ] **Step 18.1: Create property test**

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
def consumption_setups(draw):
    total_cents = draw(st.integers(min_value=1000, max_value=1_000_000))
    units_total = draw(st.integers(min_value=10, max_value=10_000))
    event_count = draw(st.integers(min_value=0, max_value=20))
    events = draw(st.lists(
        st.integers(min_value=1, max_value=units_total),
        min_size=event_count, max_size=event_count,
    ))
    return (total_cents, units_total, events)


async def _apply(setup):
    total_cents, units_total, events = setup
    engine = create_async_engine(TEST_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "TRUNCATE revrec.usage_events, revrec.recognition_events, "
                "revrec.recognition_runs, revrec.performance_obligations, "
                "revrec.contracts, gl.export_runs, recon.recon_breaks, "
                "recon.recon_runs, ledger.journal_lines, ledger.journal_entries, "
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
                total_amount_cents=total_cents, currency="USD",
                created_at=datetime.now(timezone.utc),
            )
            s.add(c)
            await s.flush()
            o = PerformanceObligation(
                id=uuid.uuid4(), contract_id=c.id, description="x",
                pattern="consumption", start_date=date(2026, 1, 1), end_date=None,
                total_amount_cents=total_cents, currency="USD",
                units_total=units_total,
                deferred_revenue_account_code="2000-DEFERRED-REV",
                revenue_account_code="4000-REV-SUB",
                created_at=datetime.now(timezone.utc),
            )
            s.add(o)
            for i, u in enumerate(events):
                s.add(UsageEvent(
                    id=uuid.uuid4(), obligation_id=o.id, units=u,
                    occurred_at=datetime.now(timezone.utc),
                    received_at=datetime.now(timezone.utc),
                    idempotency_key=f"prop-{i}-{uuid.uuid4().hex[:6]}",
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
            return int(dr), int(cr), total_cents
    finally:
        await engine.dispose()


@given(setup=consumption_setups())
@settings(max_examples=20, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_trial_balance_zero_after_consumption(setup):
    dr, cr, _ = asyncio.run(_apply(setup))
    assert dr == cr


@given(setup=consumption_setups())
@settings(max_examples=20, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_recognition_never_exceeds_commitment(setup):
    dr, _cr, total_cents = asyncio.run(_apply(setup))
    assert dr <= total_cents
```

- [ ] **Step 18.2: Run + commit**

```bash
.venv/Scripts/pytest tests/property/test_revrec_consumption_invariants.py -v
git add core/tests/property/test_revrec_consumption_invariants.py
git commit -m "test(revrec): consumption property invariants — balance + cap"
```

Expected: 2 passed (40 generated examples total).

---

## Task 19: Seed demo script extension

**Files:**
- Modify: `core/seed_revrec_demo.py`

- [ ] **Step 19.1: Append a consumption contract to the seed list**

Open `core/seed_revrec_demo.py`. Find the `contracts = [...]` list. Before the closing `]`, add a new entry:

```python
        # Usage-based contract
        {
            "ref": "I-UMBRELLA-API",
            "customer": "Umbrella Corp",
            "start": date.today() - timedelta(days=45),
            "end": None,
            "amount": 50000_00,
            "desc": "API calls committed spend",
            "pattern": "consumption",
            "units_total": 5_000_000,
            "unit_label": "API calls",
        },
```

And update the existing 3 contracts to include `"pattern": "ratable_daily"` alongside their start/end, and `"units_total": None`, `"unit_label": None` so the loop can handle both shapes. Find each of the 3 existing contract dict literals and add:

```python
            "pattern": "ratable_daily",
            "units_total": None,
            "unit_label": None,
```

Then in the seed loop, change the `PerformanceObligation(...)` call to use `c["pattern"]`, `c["units_total"]`, `c["unit_label"]` and handle the `end_date=None` case cleanly:

```python
            s.add(PerformanceObligation(
                id=uuid.uuid4(),
                contract_id=contract.id,
                description=c["desc"],
                pattern=c["pattern"],
                start_date=c["start"],
                end_date=c["end"],
                total_amount_cents=c["amount"],
                currency="USD",
                units_total=c["units_total"],
                unit_label=c["unit_label"],
                deferred_revenue_account_code="2000-DEFERRED-REV",
                revenue_account_code="4000-REV-SUB",
                created_at=now,
            ))
```

Lastly, for the consumption contract, seed a few usage events after contract/obligation insertion. After the `await s.commit()` that persists contracts+obligations, add:

```python
        # Seed usage events for the consumption obligation
        from finledger.models.revrec import UsageEvent, PerformanceObligation as _PO
        from sqlalchemy import select as _select
        async with S() as s:
            umbrella = (await s.execute(
                _select(_PO)
                .join(_PO.contract)
                .where(_PO.pattern == "consumption")
            )).scalars().first()
            if umbrella is not None:
                existing_usage = (await s.execute(
                    _select(UsageEvent).where(UsageEvent.obligation_id == umbrella.id)
                )).scalars().first()
                if existing_usage is None:
                    for i, qty in enumerate([150_000, 320_000, 275_000, 180_000]):
                        s.add(UsageEvent(
                            id=uuid.uuid4(),
                            obligation_id=umbrella.id,
                            units=qty,
                            occurred_at=now - timedelta(days=30 - (i * 7)),
                            received_at=now - timedelta(days=30 - (i * 7)),
                            idempotency_key=f"demo-usage-{i}",
                            source="api",
                        ))
                    await s.commit()
```

- [ ] **Step 19.2: Run seed + verify UI**

```bash
cd C:/Pratap/work/finledger
docker compose -f docker-compose.full.yml down -v
docker compose -f docker-compose.full.yml up -d --build
sleep 40
curl -s http://localhost:8003/revrec/waterfall -H "accept: application/json" | python -c "import sys,json; d=json.load(sys.stdin); print('total:', d['total'])"
docker compose -f docker-compose.full.yml down
```

Expected: waterfall total > 0 (the consumption obligation contributes its unrecognized portion to backlog).

- [ ] **Step 19.3: Commit**

```bash
git add core/seed_revrec_demo.py
git commit -m "chore(seed): add Umbrella Corp consumption contract to demo seed"
```

---

## Task 20: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 20.1: Append M2a-1.5a section**

In `README.md`, find the `## What M2a-1 adds (ASC 606 Step 5)` section. Immediately after it (before "Run locally"), insert:

```markdown
## What M2a-1.5a adds (committed usage drain)

- **New `consumption` recognition pattern.** Obligations now support a usage-based pattern alongside ratable and point-in-time. Recognition drains deferred revenue proportional to units consumed, capped at the contract price (ASC 606: never over-recognize).
- **`usage_events` table.** Append-only log of units consumed per obligation, with idempotency keys, `occurred_at` vs `received_at` tracking, and a pending-queue sentinel (`recognized_at IS NULL`) for the scheduler to drain.
- **Two ingestion paths.** Direct HTTP `POST /usage` for customer apps and metering middleware; Zuora `usage.uploaded` webhook via a non-posting handler in the M1 posting engine. Both write to the same table.
- **Contract-level consumption view.** `/revrec/contracts/{id}` shows units-consumed vs committed with a progress bar and a collapsed mini-table of recent events.
- **`/revrec/usage` page.** Flat list of all usage events with status pill (pending / recognized).
- **Waterfall integration.** Consumption obligations contribute their remaining `total_amount_cents - recognized_cents` to the current-month bucket (no future projection yet — usage-rate forecasts land in a later milestone).

See `docs/superpowers/specs/2026-04-21-m2a-1-5a-consumption-drain-design.md` for the full design.

Still to come: **M2a-1.5b** (pay-as-you-go, no commitment), **M2a-1.5c** (overage flagging + hybrid), CSV batch import of usage, and usage-rate projection in the waterfall.
```

- [ ] **Step 20.2: Commit**

```bash
git add README.md
git commit -m "docs: README M2a-1.5a consumption-drain section"
```

---

## Task 21: Final verification + lint

- [ ] **Step 21.1: Full test sweep**

```bash
cd core && .venv/Scripts/pytest tests/ -v 2>&1 | tail -5
```

Expected: all green; total should be ≈ 72 (M1+M2a-1 baseline) + ~25 new M2a-1.5a tests = ~97 passed, 1 skipped (Node e2e), 1 xfailed (by design).

- [ ] **Step 21.2: Lint**

```bash
.venv/Scripts/ruff check src tests
```

Expected: `All checks passed!`. If anything fails, fix it before the merge step.

- [ ] **Step 21.3: Manual demo check**

```bash
cd C:/Pratap/work/finledger
docker compose -f docker-compose.full.yml up -d --build
sleep 40
```

Visit:
- `http://localhost:8003/revrec` — Umbrella consumption contract appears in the waterfall.
- `http://localhost:8003/revrec/contracts` — Umbrella listed.
- Click Umbrella → contract detail shows the consumption progress bar with `~925,000 / 5,000,000 API calls` and the 4 seeded events.
- `http://localhost:8003/usage` — 4 usage events listed, some marked Recognized (if recognition ran during seed).

Bring down when satisfied:

```bash
docker compose -f docker-compose.full.yml down
```

---

## Task 22: Merge + tag

- [ ] **Step 22.1: Merge to master**

```bash
cd C:/Pratap/work/finledger
git checkout master
git merge --no-ff refs/heads/m2a1-5a -m "Merge branch 'm2a1-5a': FinLedger M2a-1.5a — committed usage drain

Adds the \`consumption\` recognition pattern that drains deferred revenue
proportional to units consumed, with HTTP POST and Zuora webhook
ingestion paths, batched daily recognition, and ASC-606-correct cap
semantics. ~25 new tests. Lint clean."
```

- [ ] **Step 22.2: Tag**

```bash
git tag -a m2a1-5a -m "FinLedger M2a-1.5a — committed usage drain shipped"
```

- [ ] **Step 22.3: Push**

```bash
git push origin master refs/tags/m2a1-5a refs/heads/m2a1-5a
```

Done.

---

## Self-Review

**Spec coverage checklist (cross-referenced against `2026-04-21-m2a-1-5a-consumption-drain-design.md`):**

- [x] Data model: Migration 0014 extends performance_obligations (Task 2). Migration 0015 creates usage_events (Task 3). Models extended (Task 4). Conftest truncate updated (Task 5).
- [x] Compute branch: `_compute_consumption` + dispatch (Task 6). All 7 unit test cases from spec covered.
- [x] Engine extension: pickup usage events, mark recognized (Task 7). Over-cap + mixed-pattern tests (Task 8).
- [x] Admin API: pattern='consumption' acceptance + validation (Task 9).
- [x] POST /usage endpoint: success / 409 / 404 / 422 (pattern mismatch) / 422 (units=0) (Task 10).
- [x] Zuora path: `from_zuora_usage` + `NON_POSTING_HANDLERS` dispatch (Task 11). End-to-end through recognition (Task 12). M1 posting tests still green regression (Task 11 Step 5).
- [x] GET /usage list (Task 13) with JSON + HTML branches.
- [x] Waterfall consumption branch (Task 14). JSON endpoint test still green.
- [x] Templates: revrec_usage.html (Task 15), contract detail extension (Task 16), UI smoke (Task 17).
- [x] Property invariants: trial balance zero + recognition ≤ commitment (Task 18).
- [x] Seed + README (Tasks 19, 20).
- [x] Final verification + merge + tag (Tasks 21, 22).

**Error handling matrix from spec:** every row (duplicate idempotency_key → 409; obligation not found → 404; pattern mismatch → 422; units ≤ 0 → 422; future occurred_at → 422; consumption without units_total at create → 422; full-cap events still marked recognized → Task 7 handles this path; unmatched Zuora rate_plan_charge_id → skip with INFO → Task 11 covers; non-consumption Zuora target → skip with WARN → Task 11 covers) has a corresponding test.

**Placeholder scan:** Every step has concrete code. No "similar to Task N", no TBDs, no "add appropriate error handling" without the actual code.

**Type consistency:**
- `ObligationSnapshot` gains `units_total: int | None = None` in Task 6; used with that name in Task 7 (engine), Task 18 (property test builds snapshot implicitly via real model).
- `UsageEvent` fields match exactly across migration (Task 3), model (Task 4), engine pickup (Task 7), genesis (Task 11), POST endpoint (Task 10), GET endpoint (Task 13), property test (Task 18).
- `compute_recognition(..., unprocessed_units: int = 0)` — same signature in Tasks 6, 7; older callers (M2a-1 tests) unaffected by the default.
- `NON_POSTING_HANDLERS` dispatch keys `(source, event_type)` match existing `get_mapper` signature style.
