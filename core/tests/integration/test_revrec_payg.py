import uuid
from datetime import date, datetime, timezone
import pytest
from sqlalchemy import select
from finledger.models.ledger import JournalLine, Account
from finledger.models.revrec import (
    Contract, PerformanceObligation, UsageEvent,
)
from finledger.revrec.engine import run_recognition


async def _seed_payg(session, *, price_per_unit_cents=100, ref_suffix=None):
    contract = Contract(
        id=uuid.uuid4(),
        external_ref=f"C-{ref_suffix or uuid.uuid4().hex[:8]}",
        effective_date=date(2026, 1, 1),
        status="active",
        total_amount_cents=1,
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
    assert ev.recognition_run_id == run.id


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
    # PAYG obligation
    _, payg = await _seed_payg(session, price_per_unit_cents=10, ref_suffix="payg")
    await _insert_usage(session, obligation_id=payg.id, units=200, key="mix-payg")

    # Prepaid consumption obligation
    consumption_contract = Contract(
        id=uuid.uuid4(), external_ref=f"C-cons-{uuid.uuid4().hex[:8]}",
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
        id=uuid.uuid4(), external_ref=f"C-rat-{uuid.uuid4().hex[:8]}",
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
    assert by_code_side[("1500-UNBILLED-AR", "debit")] == 2000
    assert by_code_side[("2000-DEFERRED-REV", "debit")] == 12000
    assert by_code_side[("4000-REV-SUB", "credit")] == 14000
