import json
from pathlib import Path
import pytest
from sqlalchemy import select, func
from finledger.ingest.writer import insert_source_event
from finledger.models.inbox import SourceEvent
from finledger.models.ledger import JournalEntry, JournalLine
from finledger.posting.engine import run_once


FIXTURES = Path(__file__).parents[2].parent / "fixtures"


@pytest.mark.asyncio
async def test_stripe_charge_produces_journal_entry(session):
    payload = json.loads((FIXTURES / "stripe_charge_succeeded.json").read_text())
    await insert_source_event(session, "stripe", "charge.succeeded", payload["id"], payload)
    await session.commit()

    posted = await run_once(session)
    assert posted == 1

    inbox_row = (await session.execute(select(SourceEvent))).scalar_one()
    assert inbox_row.processed_at is not None
    assert inbox_row.processing_error is None

    entries = (await session.execute(select(JournalEntry))).scalars().all()
    assert len(entries) == 1
    assert entries[0].source_event_id == inbox_row.id

    total_lines = (await session.execute(select(func.count()).select_from(JournalLine))).scalar_one()
    assert total_lines == 2


@pytest.mark.asyncio
async def test_unknown_event_type_marks_error_not_processed(session):
    await insert_source_event(session, "stripe", "does.not.exist", "evt_x", {"id": "evt_x"})
    await session.commit()
    posted = await run_once(session)
    assert posted == 0
    inbox_row = (await session.execute(select(SourceEvent))).scalar_one()
    assert inbox_row.processed_at is None
    assert "no mapper" in (inbox_row.processing_error or "")
