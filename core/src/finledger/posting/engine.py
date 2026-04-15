from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.ledger.post import post_entry
from finledger.models.inbox import SourceEvent
from finledger.posting.mappers import get_mapper, UnknownEventType


async def process_one(session: AsyncSession, event: SourceEvent) -> bool:
    """Process a single source event. Returns True if a journal entry was posted."""
    try:
        mapper = get_mapper(event.source, event.event_type)
    except UnknownEventType as e:
        event.processing_error = str(e)
        await session.flush()
        return False

    try:
        lines = mapper(event.payload)
        await post_entry(
            session,
            lines=lines,
            memo=f"{event.source}:{event.event_type}:{event.external_id}",
            source_event_id=event.id,
        )
        event.processed_at = datetime.now(timezone.utc)
        event.processing_error = None
        await session.flush()
        return True
    except Exception as e:
        event.processing_error = f"{type(e).__name__}: {e}"
        await session.flush()
        return False


async def run_once(session: AsyncSession, limit: int = 100) -> int:
    """Scan for unprocessed events and post each. Returns number successfully posted."""
    result = await session.execute(
        select(SourceEvent)
        .where(SourceEvent.processed_at.is_(None))
        .order_by(SourceEvent.received_at.asc(), SourceEvent.id.asc())
        .limit(limit)
    )
    events = result.scalars().all()
    posted_count = 0
    for event in events:
        # Each event in its own sub-transaction so a failure on one doesn't roll back others.
        async with session.begin_nested():
            if await process_one(session, event):
                posted_count += 1
    await session.commit()
    return posted_count
