import uuid
from datetime import date, datetime, timezone
import pytest
from sqlalchemy import select, func
from finledger.ledger.accounts import get_account_id
from finledger.models.ledger import JournalEntry, JournalLine, Account
from finledger.models.revrec import Contract, PerformanceObligation, RecognitionRun, RecognitionEvent
from finledger.revrec.engine import run_recognition


async def _seed_contract_and_obligation(session, *, total, start, end, pattern="ratable_daily"):
    contract = Contract(
        id=uuid.uuid4(),
        external_ref=f"TEST-{uuid.uuid4().hex[:8]}",
        effective_date=start,
        status="active",
        total_amount_cents=total,
        currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    session.add(contract)
    await session.flush()
    obligation = PerformanceObligation(
        id=uuid.uuid4(),
        contract_id=contract.id,
        description="Test obligation",
        pattern=pattern,
        start_date=start,
        end_date=end,
        total_amount_cents=total,
        currency="USD",
        deferred_revenue_account_code="2000-DEFERRED-REV",
        revenue_account_code="4000-REV-SUB",
        created_at=datetime.now(timezone.utc),
    )
    session.add(obligation)
    await session.flush()
    return contract, obligation


@pytest.mark.asyncio
async def test_run_recognition_posts_journal_entry_and_records_event(session):
    _, obl = await _seed_contract_and_obligation(
        session, total=31000, start=date(2026, 5, 1), end=date(2026, 5, 31),
    )
    await session.commit()

    run = await run_recognition(session, through_date=date(2026, 5, 10))
    await session.commit()

    assert run.obligations_processed == 1
    assert run.total_recognized_cents == 10 * 1000
    assert run.journal_entry_id is not None

    entry = (await session.execute(
        select(JournalEntry).where(JournalEntry.id == run.journal_entry_id)
    )).scalar_one()
    assert entry.memo == "revrec:run:2026-05-10"

    lines = (await session.execute(
        select(JournalLine, Account.code)
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == entry.id)
    )).all()
    by_code_side = {(code, line.side): line.amount_cents for line, code in lines}
    assert by_code_side[("2000-DEFERRED-REV", "debit")] == 10000
    assert by_code_side[("4000-REV-SUB", "credit")] == 10000

    events = (await session.execute(
        select(RecognitionEvent).where(RecognitionEvent.run_id == run.id)
    )).scalars().all()
    assert len(events) == 1
    assert events[0].obligation_id == obl.id
    assert events[0].recognized_cents == 10000
    assert events[0].recognized_through == date(2026, 5, 10)
