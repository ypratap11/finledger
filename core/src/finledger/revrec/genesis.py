import uuid
from datetime import date, datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.models.revrec import Contract, PerformanceObligation


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


async def from_zuora_invoice(
    session: AsyncSession,
    payload: dict,
    source_event_id: uuid.UUID,
) -> Contract | None:
    """If the invoice carries service_period_start/end metadata, create a contract
    and one ratable obligation. Idempotent by invoice number -> contract.external_ref."""
    inv = payload.get("invoice") or {}
    metadata = inv.get("metadata") or {}
    start_s = metadata.get("service_period_start")
    end_s = metadata.get("service_period_end")
    if not start_s or not end_s:
        return None

    invoice_number = inv["invoiceNumber"]
    existing = (await session.execute(
        select(Contract).where(Contract.external_ref == invoice_number)
    )).scalar_one_or_none()
    if existing is not None:
        return existing

    start = _parse_date(start_s)
    end = _parse_date(end_s)
    amount = int(inv["amount"])
    currency = inv.get("currency", "USD").upper()
    customer_id = inv.get("accountId")

    contract = Contract(
        id=uuid.uuid4(),
        external_ref=invoice_number,
        customer_id=customer_id,
        effective_date=start,
        status="active",
        total_amount_cents=amount,
        currency=currency,
        created_from_event_id=source_event_id,
        created_at=datetime.now(timezone.utc),
    )
    session.add(contract)
    await session.flush()

    obligation = PerformanceObligation(
        id=uuid.uuid4(),
        contract_id=contract.id,
        description=f"Subscription - {invoice_number}",
        pattern="ratable_daily",
        start_date=start,
        end_date=end,
        total_amount_cents=amount,
        currency=currency,
        deferred_revenue_account_code="2000-DEFERRED-REV",
        revenue_account_code="4000-REV-SUB",
        created_at=datetime.now(timezone.utc),
    )
    session.add(obligation)
    await session.flush()
    return contract
