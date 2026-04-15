import json
import pytest
from finledger.ingest.writer import insert_source_event
from finledger.ingest.hash_chain import GENESIS_HASH, compute_row_hash


@pytest.mark.asyncio
async def test_insert_first_event_uses_genesis_prev_hash(session):
    payload = {"id": "evt_1", "type": "charge.succeeded"}
    row = await insert_source_event(
        session, source="stripe", event_type="charge.succeeded",
        external_id="evt_1", payload=payload,
    )
    await session.commit()
    assert row.prev_hash == GENESIS_HASH
    expected = compute_row_hash(
        GENESIS_HASH, "stripe", "evt_1",
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    )
    assert row.row_hash == expected


@pytest.mark.asyncio
async def test_insert_second_event_chains_from_first(session):
    a = await insert_source_event(session, "stripe", "charge.succeeded", "evt_1", {"n": 1})
    await session.commit()
    b = await insert_source_event(session, "stripe", "charge.succeeded", "evt_2", {"n": 2})
    await session.commit()
    assert b.prev_hash == a.row_hash


@pytest.mark.asyncio
async def test_duplicate_external_id_raises(session):
    await insert_source_event(session, "stripe", "charge.succeeded", "evt_1", {"n": 1})
    await session.commit()
    with pytest.raises(Exception):
        await insert_source_event(session, "stripe", "charge.succeeded", "evt_1", {"n": 1})
        await session.commit()
