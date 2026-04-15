import json
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.ingest.hash_chain import GENESIS_HASH, compute_row_hash
from finledger.models.inbox import SourceEvent


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


async def _get_last_row_hash(session: AsyncSession) -> bytes:
    result = await session.execute(
        select(SourceEvent.row_hash).order_by(SourceEvent.received_at.desc(), SourceEvent.id.desc()).limit(1)
    )
    row = result.first()
    return row[0] if row else GENESIS_HASH


async def insert_source_event(
    session: AsyncSession,
    source: str,
    event_type: str,
    external_id: str,
    payload: dict,
) -> SourceEvent:
    prev = await _get_last_row_hash(session)
    body = _canonical_bytes(payload)
    row_hash = compute_row_hash(prev, source, external_id, body)
    event = SourceEvent(
        id=uuid.uuid4(),
        source=source,
        event_type=event_type,
        external_id=external_id,
        idempotency_key=f"{source}:{external_id}",
        payload=payload,
        received_at=datetime.now(timezone.utc),
        prev_hash=prev,
        row_hash=row_hash,
        processed_at=None,
        processing_error=None,
    )
    session.add(event)
    await session.flush()
    return event
