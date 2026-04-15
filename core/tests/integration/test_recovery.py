import json
from pathlib import Path
from unittest.mock import patch
import pytest
from sqlalchemy import select, func
from finledger.ingest.writer import insert_source_event
from finledger.models.inbox import SourceEvent
from finledger.models.ledger import JournalEntry
from finledger.posting.engine import run_once


FIXTURES = Path(__file__).parents[2].parent / "fixtures"


@pytest.mark.asyncio
async def test_crash_in_mapper_leaves_row_unprocessed_and_retry_succeeds(session):
    payload = json.loads((FIXTURES / "stripe_charge_succeeded.json").read_text())
    await insert_source_event(session, "stripe", "charge.succeeded", payload["id"], payload)
    await session.commit()

    def boom(_):
        raise RuntimeError("simulated mapper crash")

    with patch("finledger.posting.engine.get_mapper", return_value=boom):
        posted = await run_once(session)
    assert posted == 0

    row = (await session.execute(select(SourceEvent))).scalar_one()
    assert row.processed_at is None
    assert "simulated mapper crash" in (row.processing_error or "")

    entries = (await session.execute(select(func.count()).select_from(JournalEntry))).scalar_one()
    assert entries == 0

    posted = await run_once(session)
    assert posted == 1
    entries = (await session.execute(select(func.count()).select_from(JournalEntry))).scalar_one()
    assert entries == 1
