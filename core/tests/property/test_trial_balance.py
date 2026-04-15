import asyncio
import uuid
from hypothesis import given, settings, HealthCheck
from sqlalchemy import select, func, case, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from finledger.ingest.writer import insert_source_event
from finledger.ledger.accounts import seed_chart_of_accounts
from finledger.models.ledger import JournalLine
from finledger.posting.engine import run_once
from tests.property.strategies import event_sequences
from tests.integration.conftest import TEST_URL


async def _reset_and_apply(events) -> tuple[int, int]:
    engine = create_async_engine(TEST_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "TRUNCATE gl.export_runs, recon.recon_breaks, recon.recon_runs, "
                "ledger.journal_lines, ledger.journal_entries, ledger.accounts, "
                "inbox.source_events RESTART IDENTITY CASCADE"
            ))
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        async with SessionLocal() as s:
            await seed_chart_of_accounts(s)
            await s.commit()
        async with SessionLocal() as s:
            used_ids = set()
            for (source, event_type, payload) in events:
                ext_id = payload.get("id") or payload["invoice"]["id"]
                if ext_id in used_ids:
                    ext_id = f"{ext_id}-{uuid.uuid4().hex[:6]}"
                used_ids.add(ext_id)
                await insert_source_event(s, source, event_type, ext_id, payload)
            await s.commit()
            await run_once(s)
        async with SessionLocal() as s:
            result = await s.execute(
                select(
                    func.coalesce(func.sum(case((JournalLine.side == "debit", JournalLine.amount_cents), else_=0)), 0),
                    func.coalesce(func.sum(case((JournalLine.side == "credit", JournalLine.amount_cents), else_=0)), 0),
                )
            )
            dr, cr = result.one()
            return int(dr), int(cr)
    finally:
        await engine.dispose()


@given(events=event_sequences())
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_trial_balance_always_zero(events):
    dr, cr = asyncio.run(_reset_and_apply(events))
    assert dr == cr, f"dr={dr} cr={cr} (diff={dr - cr})"
