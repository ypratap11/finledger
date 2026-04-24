import uuid
from datetime import date, datetime, timezone
import pytest
from sqlalchemy import select
from finledger.models.ledger import JournalEntry, JournalLine, Account
from finledger.models.revrec import (
    Contract, PerformanceObligation, UsageEvent,
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

    picked = (await session.execute(
        select(UsageEvent).where(UsageEvent.obligation_id == obl.id)
    )).scalar_one()
    assert picked.recognized_at is not None
    assert picked.recognition_run_id == run.id


@pytest.mark.asyncio
async def test_consumption_over_cap_recognition_caps_at_commitment(session):
    _, obl = await _seed_consumption_obligation(
        session, total_cents=10000, units_total=1000,
    )
    await _insert_usage(session, obligation_id=obl.id, units=1500, key="ev-over")
    await session.commit()

    run = await run_recognition(session, through_date=date(2026, 5, 1))
    await session.commit()

    assert run.total_recognized_cents == 10000

    ev = (await session.execute(select(UsageEvent))).scalar_one()
    assert ev.recognized_at is not None
    assert ev.recognition_run_id == run.id


@pytest.mark.asyncio
async def test_mixed_ratable_and_consumption_same_run(session):
    _, ratable_ob = await _seed_consumption_obligation(
        session, total_cents=10000, units_total=1000,
    )
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

    # Consumption: 500/2000 of $200 = $50 = 5000
    # Ratable: 10 days of $10000/31 = floor(10000/31) * 10 = 322 * 10 = 3220
    assert run.obligations_processed == 2
    assert 3000 <= run.total_recognized_cents - 5000 <= 3300
