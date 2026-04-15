import json
from pathlib import Path
import pytest
from sqlalchemy import select, func
from finledger.ingest.writer import insert_source_event
from finledger.models.ledger import JournalEntry
from finledger.posting.engine import run_once


FIXTURES = Path(__file__).parents[2].parent / "fixtures"


@pytest.mark.asyncio
async def test_duplicate_external_id_produces_one_journal_entry(session):
    payload = json.loads((FIXTURES / "stripe_charge_succeeded.json").read_text())
    await insert_source_event(session, "stripe", "charge.succeeded", payload["id"], payload)
    await session.commit()
    with pytest.raises(Exception):
        await insert_source_event(session, "stripe", "charge.succeeded", payload["id"], payload)
        await session.commit()
    await session.rollback()
    await run_once(session)
    count = (await session.execute(select(func.count()).select_from(JournalEntry))).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_run_once_is_idempotent(session):
    payload = json.loads((FIXTURES / "stripe_charge_succeeded.json").read_text())
    await insert_source_event(session, "stripe", "charge.succeeded", payload["id"], payload)
    await session.commit()
    assert await run_once(session) == 1
    assert await run_once(session) == 0
    count = (await session.execute(select(func.count()).select_from(JournalEntry))).scalar_one()
    assert count == 1
