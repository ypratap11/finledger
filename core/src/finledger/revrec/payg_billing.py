"""PAYG billing reclassification.

When Zuora's invoice.posted event references a consumption_payg obligation,
the credit side of the JE is the obligation's unbilled-AR contract asset
account, not Deferred Revenue — because revenue was already recognized via
usage events. This module rewrites the mapper-produced lines accordingly
and records a PaygReclassification row.
"""
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.ledger.post import LineSpec
from finledger.models.revrec import PerformanceObligation, PaygReclassification

log = logging.getLogger(__name__)


async def reclassify_payg_invoice(
    session: AsyncSession,
    payload: dict,
    lines: list[LineSpec],
    source_event_id: uuid.UUID,
) -> tuple[list[LineSpec], PaygReclassification | None]:
    """If the invoice references a consumption_payg obligation via
    metadata.payg_obligation_ref, rewrite the credit-side accounts on the
    produced lines from the default Deferred Revenue to the obligation's
    unbilled_ar_account_code, and prepare a PaygReclassification record
    (caller fills journal_entry_id after posting).

    Returns (rewritten_lines, pending_reclassification_or_None).
    """
    inv = payload.get("invoice") or {}
    metadata = inv.get("metadata") or {}
    obligation_ref = metadata.get("payg_obligation_ref")
    if not obligation_ref:
        return lines, None

    obligation = (await session.execute(
        select(PerformanceObligation).where(PerformanceObligation.external_ref == obligation_ref)
    )).scalar_one_or_none()
    if obligation is None:
        log.info(f"payg_obligation_ref={obligation_ref!r} matched no obligation; skipping reclassification")
        return lines, None
    if obligation.pattern != "consumption_payg":
        log.warning(
            f"payg_obligation_ref={obligation_ref!r} matched obligation with pattern "
            f"{obligation.pattern!r}, not consumption_payg; skipping reclassification"
        )
        return lines, None

    # Rewrite credit lines that point at the deferred revenue account.
    rewritten: list[LineSpec] = []
    rewrite_total = 0
    for line in lines:
        if line.side == "credit" and line.account_code == obligation.deferred_revenue_account_code:
            rewritten.append(LineSpec(
                account_code=obligation.unbilled_ar_account_code,
                side="credit",
                amount_cents=line.amount_cents,
                currency=line.currency,
                external_ref=line.external_ref,
                dimension_json=line.dimension_json,
            ))
            rewrite_total += line.amount_cents
        else:
            rewritten.append(line)

    if rewrite_total <= 0:
        log.info("invoice has no credit line on the obligation's deferred-rev account; nothing to reclassify")
        return lines, None

    invoice_number = inv.get("invoiceNumber")
    pending = PaygReclassification(
        id=uuid.uuid4(),
        obligation_id=obligation.id,
        amount_cents=rewrite_total,
        invoice_external_ref=invoice_number,
        billed_at=datetime.now(timezone.utc),
        journal_entry_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),  # caller fills
        source_event_id=source_event_id,
    )
    return rewritten, pending
