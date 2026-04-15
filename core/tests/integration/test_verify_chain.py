import pytest
from sqlalchemy import text
from finledger.ingest.writer import insert_source_event
from finledger.verify_chain import verify_chain, ChainBreak


@pytest.mark.asyncio
async def test_verify_passes_on_intact_chain(session):
    await insert_source_event(session, "stripe", "charge.succeeded", "evt_1", {"n": 1})
    await insert_source_event(session, "stripe", "charge.succeeded", "evt_2", {"n": 2})
    await session.commit()
    assert await verify_chain_sync_ok(session) is True


@pytest.mark.asyncio
async def test_verify_fails_when_payload_mutated(session):
    await insert_source_event(session, "stripe", "charge.succeeded", "evt_1", {"n": 1})
    await insert_source_event(session, "stripe", "charge.succeeded", "evt_2", {"n": 2})
    await session.commit()
    await session.execute(
        text("UPDATE inbox.source_events SET payload = CAST(:p AS jsonb) WHERE external_id = 'evt_1'"),
        {"p": '{"n":999}'},
    )
    await session.commit()
    with pytest.raises(ChainBreak):
        await verify_chain(session)


async def verify_chain_sync_ok(session) -> bool:
    await verify_chain(session)
    return True
