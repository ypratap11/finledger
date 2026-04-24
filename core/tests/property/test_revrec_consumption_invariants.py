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
