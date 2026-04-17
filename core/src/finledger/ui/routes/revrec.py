import uuid
from datetime import date, datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.db import SessionLocal, SyncSessionLocal
from finledger.models.revrec import Contract, PerformanceObligation


router = APIRouter()


async def get_async_session():
    async with SessionLocal() as s:
        yield s


def get_sync_session():
    with SyncSessionLocal() as s:
        yield s


class ContractIn(BaseModel):
    external_ref: str
    customer_id: str | None = None
    effective_date: date
    total_amount_cents: int
    currency: str = "USD"


class ContractOut(BaseModel):
    id: UUID
    external_ref: str


@router.post("/contracts", status_code=201, response_model=ContractOut)
async def create_contract(body: ContractIn, session: AsyncSession = Depends(get_async_session)):
    existing = (await session.execute(
        select(Contract).where(Contract.external_ref == body.external_ref)
    )).scalar_one_or_none()
    if existing is not None:
        return ContractOut(id=existing.id, external_ref=existing.external_ref)

    contract = Contract(
        id=uuid.uuid4(),
        external_ref=body.external_ref,
        customer_id=body.customer_id,
        effective_date=body.effective_date,
        status="active",
        total_amount_cents=body.total_amount_cents,
        currency=body.currency,
        created_at=datetime.now(timezone.utc),
    )
    session.add(contract)
    await session.commit()
    return ContractOut(id=contract.id, external_ref=contract.external_ref)
