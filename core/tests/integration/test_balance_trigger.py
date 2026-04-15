import uuid
from datetime import datetime, timezone
import pytest
from finledger.ledger.accounts import get_account_id
from finledger.models.ledger import JournalEntry, JournalLine


@pytest.mark.asyncio
async def test_balanced_entry_commits(session):
    cash = await get_account_id(session, "1000-CASH")
    ar = await get_account_id(session, "1200-AR")
    entry = JournalEntry(id=uuid.uuid4(), posted_at=datetime.now(timezone.utc), status="posted")
    session.add(entry)
    await session.flush()
    session.add(JournalLine(id=uuid.uuid4(), entry_id=entry.id, account_id=cash, side="debit", amount_cents=1000, currency="USD"))
    session.add(JournalLine(id=uuid.uuid4(), entry_id=entry.id, account_id=ar, side="credit", amount_cents=1000, currency="USD"))
    await session.commit()


@pytest.mark.asyncio
async def test_unbalanced_entry_is_rejected(session):
    cash = await get_account_id(session, "1000-CASH")
    ar = await get_account_id(session, "1200-AR")
    entry = JournalEntry(id=uuid.uuid4(), posted_at=datetime.now(timezone.utc), status="posted")
    session.add(entry)
    await session.flush()
    session.add(JournalLine(id=uuid.uuid4(), entry_id=entry.id, account_id=cash, side="debit", amount_cents=1000, currency="USD"))
    session.add(JournalLine(id=uuid.uuid4(), entry_id=entry.id, account_id=ar, side="credit", amount_cents=999, currency="USD"))
    with pytest.raises(Exception) as excinfo:
        await session.commit()
    assert "unbalanced" in str(excinfo.value).lower()


@pytest.mark.xfail(
    reason="Balance trigger fires on journal_lines; an entry with zero lines never triggers it. "
    "Enforcement for empty entries is the post_entry helper's responsibility (see Task 12).",
    strict=True,
)
@pytest.mark.asyncio
async def test_entry_with_no_lines_is_rejected(session):
    entry = JournalEntry(id=uuid.uuid4(), posted_at=datetime.now(timezone.utc), status="posted")
    session.add(entry)
    with pytest.raises(Exception):
        await session.commit()
