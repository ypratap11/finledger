import asyncio
import uuid
from datetime import date, datetime, timezone, timedelta
from hypothesis import given, settings, HealthCheck, strategies as st
from sqlalchemy import func, select, text, case
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from finledger.ledger.accounts import seed_chart_of_accounts
from finledger.models.revrec import Contract, PerformanceObligation
from finledger.models.ledger import JournalLine
from finledger.revrec.engine import run_recognition
from tests.integration.conftest import TEST_URL


@st.composite
def obligation_specs(draw):
    total = draw(st.integers(min_value=100, max_value=1_000_000))
    start = draw(st.dates(min_value=date(2026, 1, 1), max_value=date(2026, 6, 1)))
    days = draw(st.integers(min_value=1, max_value=120))
    pattern = draw(st.sampled_from(["ratable_daily", "point_in_time"]))
    end = start + timedelta(days=days) if pattern == "ratable_daily" else None
    return (total, start, end, pattern)


async def _apply(obligations):
    engine = create_async_engine(TEST_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "TRUNCATE revrec.recognition_events, revrec.recognition_runs, "
                "revrec.performance_obligations, revrec.contracts, "
                "gl.export_runs, recon.recon_breaks, recon.recon_runs, "
                "ledger.journal_lines, ledger.journal_entries, ledger.accounts, "
                "inbox.source_events RESTART IDENTITY CASCADE"
            ))
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionLocal() as s:
            await seed_chart_of_accounts(s)
            await s.commit()

        latest = date(2026, 1, 1)
        total_amount = 0
        async with SessionLocal() as s:
            for total, start, end, pattern in obligations:
                c = Contract(
                    id=uuid.uuid4(), external_ref=f"P-{uuid.uuid4().hex[:8]}",
                    effective_date=start, status="active",
                    total_amount_cents=total, currency="USD",
                    created_at=datetime.now(timezone.utc),
                )
                s.add(c)
                await s.flush()
                o = PerformanceObligation(
                    id=uuid.uuid4(), contract_id=c.id, description="x",
                    pattern=pattern, start_date=start, end_date=end,
                    total_amount_cents=total, currency="USD",
                    deferred_revenue_account_code="2000-DEFERRED-REV",
                    revenue_account_code="4000-REV-SUB",
                    created_at=datetime.now(timezone.utc),
                )
                s.add(o)
                total_amount += total
                if end is not None and end > latest:
                    latest = end
                if end is None and start > latest:
                    latest = start
            await s.commit()
        async with SessionLocal() as s:
            await run_recognition(s, through_date=latest + timedelta(days=1))
            await s.commit()
        async with SessionLocal() as s:
            dr, cr = (await s.execute(
                select(
                    func.coalesce(func.sum(case((JournalLine.side == "debit", JournalLine.amount_cents), else_=0)), 0),
                    func.coalesce(func.sum(case((JournalLine.side == "credit", JournalLine.amount_cents), else_=0)), 0),
                )
            )).one()
            return int(dr), int(cr), total_amount
    finally:
        await engine.dispose()


@given(obligations=st.lists(obligation_specs(), min_size=1, max_size=10))
@settings(max_examples=20, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_trial_balance_zero_after_full_recognition(obligations):
    dr, cr, _total = asyncio.run(_apply(obligations))
    assert dr == cr


@given(obligations=st.lists(obligation_specs(), min_size=1, max_size=10))
@settings(max_examples=20, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_full_recognition_recognizes_exact_total(obligations):
    dr, _cr, total = asyncio.run(_apply(obligations))
    assert dr == total
