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


class ObligationIn(BaseModel):
    description: str
    pattern: str
    start_date: date
    end_date: date | None = None
    total_amount_cents: int
    currency: str = "USD"
    deferred_revenue_account_code: str = "2000-DEFERRED-REV"
    revenue_account_code: str = "4000-REV-SUB"


class ObligationOut(BaseModel):
    id: UUID


@router.post("/contracts/{contract_id}/obligations", status_code=201, response_model=ObligationOut)
async def create_obligation(
    contract_id: UUID, body: ObligationIn,
    session: AsyncSession = Depends(get_async_session),
):
    if body.pattern == "ratable_daily" and body.end_date is None:
        raise HTTPException(422, "ratable_daily requires end_date")
    if body.pattern not in ("ratable_daily", "point_in_time"):
        raise HTTPException(422, f"unknown pattern: {body.pattern}")
    if body.end_date is not None and body.end_date < body.start_date:
        raise HTTPException(422, "end_date before start_date")

    contract = (await session.execute(
        select(Contract).where(Contract.id == contract_id)
    )).scalar_one_or_none()
    if contract is None:
        raise HTTPException(404, "contract not found")

    obl = PerformanceObligation(
        id=uuid.uuid4(),
        contract_id=contract_id,
        description=body.description,
        pattern=body.pattern,
        start_date=body.start_date,
        end_date=body.end_date,
        total_amount_cents=body.total_amount_cents,
        currency=body.currency,
        deferred_revenue_account_code=body.deferred_revenue_account_code,
        revenue_account_code=body.revenue_account_code,
        created_at=datetime.now(timezone.utc),
    )
    session.add(obl)
    await session.commit()
    return ObligationOut(id=obl.id)
