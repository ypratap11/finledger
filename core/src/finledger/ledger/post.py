import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.models.ledger import JournalEntry, JournalLine


@dataclass
class LineSpec:
    account_code: str
    side: str  # 'debit' | 'credit'
    amount_cents: int
    currency: str = "USD"
    external_ref: str | None = None
    dimension_json: dict[str, Any] | None = None


async def post_entry(
    session: AsyncSession,
    *,
    lines: list[LineSpec],
    memo: str | None = None,
    source_event_id: uuid.UUID | None = None,
    status: str = "posted",
) -> JournalEntry:
    from finledger.ledger.accounts import get_account_id

    total_dr = sum(l.amount_cents for l in lines if l.side == "debit")
    total_cr = sum(l.amount_cents for l in lines if l.side == "credit")
    if total_dr != total_cr:
        raise ValueError(f"unbalanced: dr={total_dr} cr={total_cr}")
    if total_dr == 0:
        raise ValueError("no lines")

    entry = JournalEntry(
        id=uuid.uuid4(),
        source_event_id=source_event_id,
        posted_at=datetime.now(timezone.utc),
        status=status,
        memo=memo,
    )
    session.add(entry)
    await session.flush()

    for spec in lines:
        account_id = await get_account_id(session, spec.account_code)
        session.add(JournalLine(
            id=uuid.uuid4(),
            entry_id=entry.id,
            account_id=account_id,
            side=spec.side,
            amount_cents=spec.amount_cents,
            currency=spec.currency,
            external_ref=spec.external_ref,
            dimension_json=spec.dimension_json or {},
        ))
    await session.flush()
    return entry
