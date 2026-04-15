import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.ledger.accounts import get_account_id
from finledger.models.ledger import JournalLine
from finledger.models.recon import ReconBreak, ReconRun


@dataclass
class StripeBalanceTx:
    charge_id: str
    amount_cents: int
    currency: str
    created: datetime


async def run_stripe_ledger_recon(
    session: AsyncSession,
    *,
    stripe_txs: list[StripeBalanceTx],
    period_start: date,
    period_end: date,
) -> ReconRun:
    """Match Stripe balance transactions to ledger CASH debits by charge id."""
    run = ReconRun(
        id=uuid.uuid4(),
        recon_type="stripe_ledger",
        period_start=period_start,
        period_end=period_end,
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    await session.flush()

    cash_account_id = await get_account_id(session, "1000-CASH")
    ledger_lines = (
        await session.execute(
            select(JournalLine).where(
                JournalLine.account_id == cash_account_id,
                JournalLine.side == "debit",
                JournalLine.external_ref.isnot(None),
            )
        )
    ).scalars().all()
    ledger_by_ref: dict[str, JournalLine] = {l.external_ref: l for l in ledger_lines}
    external_by_ref: dict[str, StripeBalanceTx] = {tx.charge_id: tx for tx in stripe_txs}

    matched = unmatched = mismatched = 0

    for ref, tx in external_by_ref.items():
        ledger = ledger_by_ref.get(ref)
        if ledger is None:
            unmatched += 1
            session.add(ReconBreak(
                id=uuid.uuid4(), run_id=run.id, kind="unmatched_external",
                external_ref=ref, external_amount_cents=tx.amount_cents,
                details={"currency": tx.currency},
            ))
            continue
        if ledger.amount_cents != tx.amount_cents:
            mismatched += 1
            session.add(ReconBreak(
                id=uuid.uuid4(), run_id=run.id, kind="amount_mismatch",
                external_ref=ref, external_amount_cents=tx.amount_cents,
                ledger_amount_cents=ledger.amount_cents,
                details={},
            ))
        else:
            matched += 1

    for ref, line in ledger_by_ref.items():
        if ref not in external_by_ref:
            unmatched += 1
            session.add(ReconBreak(
                id=uuid.uuid4(), run_id=run.id, kind="unmatched_ledger",
                external_ref=ref, ledger_amount_cents=line.amount_cents,
                details={},
            ))

    run.matched_count = matched
    run.unmatched_count = unmatched
    run.mismatched_count = mismatched
    run.finished_at = datetime.now(timezone.utc)
    await session.flush()
    return run
