import asyncio
import uuid
from hypothesis import given, settings, HealthCheck
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from finledger.ingest.writer import insert_source_event
from finledger.ledger.accounts import seed_chart_of_accounts
from finledger.models.ledger import JournalLine
from finledger.posting.engine import run_once
from tests.property.strategies import event_sequences
from tests.integration.conftest import TEST_URL


async def _balance_snapshot(session) -> list[tuple[str, int]]:
    rows = (await session.execute(
        select(JournalLine.account_id, JournalLine.side, JournalLine.amount_cents)
    )).all()
    totals: dict[tuple[str, str], int] = {}
    for account_id, side, amt in rows:
        key = (str(account_id), side)
        totals[key] = totals.get(key, 0) + amt
    return sorted((f"{k[0]}:{k[1]}", v) for k, v in totals.items())


async def _apply_events(events) -> tuple[list, list]:
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
        used_ids = set()
        async with SessionLocal() as s:
            for (source, event_type, payload) in events:
                ext_id = payload.get("id") or payload["invoice"]["id"]
                if ext_id in used_ids:
                    ext_id = f"{ext_id}-{uuid.uuid4().hex[:6]}"
                used_ids.add(ext_id)
                await insert_source_event(s, source, event_type, ext_id, payload)
            await s.commit()
            await run_once(s)
        async with SessionLocal() as s:
            snap = await _balance_snapshot(s)

        async with engine.begin() as conn:
            await conn.execute(text(
                "TRUNCATE ledger.journal_lines, ledger.journal_entries, ledger.accounts "
                "RESTART IDENTITY CASCADE"
            ))
            await conn.execute(text("UPDATE inbox.source_events SET processed_at = NULL, processing_error = NULL"))
        async with SessionLocal() as s:
            await seed_chart_of_accounts(s)
            await s.commit()
        async with SessionLocal() as s:
            await run_once(s)
        async with SessionLocal() as s:
            snap_replayed = await _balance_snapshot(s)
        return snap, snap_replayed
    finally:
        await engine.dispose()


@given(events=event_sequences())
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_replaying_inbox_reproduces_ledger(events):
    snap_a, snap_b = asyncio.run(_apply_events(events))
    totals_a = sum(v for k, v in snap_a if k.endswith(":debit"))
    totals_b = sum(v for k, v in snap_b if k.endswith(":debit"))
    assert totals_a == totals_b
