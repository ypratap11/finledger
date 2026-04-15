import asyncio
import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.db import SessionLocal
from finledger.ingest.hash_chain import GENESIS_HASH, compute_row_hash
from finledger.models.inbox import SourceEvent


class ChainBreak(Exception):
    pass


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


async def verify_chain(session: AsyncSession) -> int:
    result = await session.execute(
        select(SourceEvent).order_by(SourceEvent.received_at.asc(), SourceEvent.id.asc())
    )
    rows = result.scalars().all()
    expected_prev = GENESIS_HASH
    for idx, row in enumerate(rows):
        if row.prev_hash != expected_prev:
            raise ChainBreak(f"prev_hash mismatch at row {idx} (external_id={row.external_id})")
        expected_row = compute_row_hash(
            expected_prev, row.source, row.external_id, _canonical_bytes(row.payload)
        )
        if row.row_hash != expected_row:
            raise ChainBreak(f"row_hash mismatch at row {idx} (external_id={row.external_id})")
        expected_prev = row.row_hash
    return len(rows)


async def _main() -> None:
    async with SessionLocal() as s:
        count = await verify_chain(s)
        print(f"OK: verified {count} rows")


if __name__ == "__main__":
    asyncio.run(_main())
