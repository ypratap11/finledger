import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.models.ledger import Account

CHART = [
    ("1000-CASH", "Cash", "asset", "debit"),
    ("1200-AR", "Accounts Receivable", "asset", "debit"),
    ("2000-DEFERRED-REV", "Deferred Revenue", "liability", "credit"),
    ("4000-REV-SUB", "Revenue — Subscription", "revenue", "credit"),
    ("4100-REV-USAGE", "Revenue — Usage", "revenue", "credit"),
]


async def seed_chart_of_accounts(session: AsyncSession) -> None:
    existing = await session.execute(select(Account.code))
    existing_codes = {c for (c,) in existing}
    for code, name, acct_type, side in CHART:
        if code in existing_codes:
            continue
        session.add(Account(id=uuid.uuid4(), code=code, name=name, type=acct_type, normal_side=side))
    await session.flush()


async def get_account_id(session: AsyncSession, code: str) -> uuid.UUID:
    result = await session.execute(select(Account.id).where(Account.code == code))
    row = result.first()
    if row is None:
        raise LookupError(f"account not found: {code}")
    return row[0]
