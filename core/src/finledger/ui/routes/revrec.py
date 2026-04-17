import uuid
from datetime import date, datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
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


class RunIn(BaseModel):
    through_date: date


class RunOut(BaseModel):
    id: UUID
    run_through_date: date
    obligations_processed: int
    total_recognized_cents: int
    journal_entry_id: UUID | None


@router.post("/run", response_model=RunOut)
async def trigger_run(body: RunIn, session: AsyncSession = Depends(get_async_session)):
    from finledger.revrec.engine import run_recognition
    run = await run_recognition(session, through_date=body.through_date)
    await session.commit()
    return RunOut(
        id=run.id,
        run_through_date=run.run_through_date,
        obligations_processed=run.obligations_processed,
        total_recognized_cents=run.total_recognized_cents,
        journal_entry_id=run.journal_entry_id,
    )


def _wants_json(request: Request) -> bool:
    return "application/json" in (request.headers.get("accept") or "")


@router.get("/contracts")
async def list_contracts(request: Request, session: AsyncSession = Depends(get_async_session)):
    rows = (await session.execute(
        select(Contract).order_by(Contract.created_at.desc())
    )).scalars().all()
    data = {
        "contracts": [
            {"id": str(c.id), "external_ref": c.external_ref,
             "customer_id": c.customer_id, "status": c.status,
             "total_amount_cents": c.total_amount_cents, "currency": c.currency}
            for c in rows
        ]
    }
    if _wants_json(request):
        return JSONResponse(data)
    return request.app.state.templates.TemplateResponse(
        request=request, name="revrec_contract_list.html", context={"contracts": rows},
    )


@router.get("/runs")
async def list_runs(request: Request, session: AsyncSession = Depends(get_async_session)):
    from finledger.models.revrec import RecognitionRun
    rows = (await session.execute(
        select(RecognitionRun).order_by(RecognitionRun.started_at.desc()).limit(50)
    )).scalars().all()
    data = {
        "runs": [
            {"id": str(r.id), "run_through_date": r.run_through_date.isoformat(),
             "obligations_processed": r.obligations_processed,
             "total_recognized_cents": r.total_recognized_cents,
             "journal_entry_id": str(r.journal_entry_id) if r.journal_entry_id else None}
            for r in rows
        ]
    }
    if _wants_json(request):
        return JSONResponse(data)
    return request.app.state.templates.TemplateResponse(
        request=request, name="revrec_runs.html", context={"runs": rows},
    )


@router.get("/waterfall")
async def waterfall(
    request: Request,
    months: int = 12,
    session: AsyncSession = Depends(get_async_session),
):
    from finledger.revrec.waterfall import project_obligation_by_month, BEYOND_KEY
    from finledger.models.revrec import RecognitionEvent

    today = date.today()
    obligations = (await session.execute(
        select(PerformanceObligation).join(PerformanceObligation.contract)
        .where(PerformanceObligation.contract.has(status="active"))
    )).scalars().all()

    already_rows = (await session.execute(
        select(
            RecognitionEvent.obligation_id,
            func.coalesce(func.sum(RecognitionEvent.recognized_cents), 0),
            func.max(RecognitionEvent.recognized_through),
        ).group_by(RecognitionEvent.obligation_id)
    )).all()
    already_map = {oid: (int(cents), through) for oid, cents, through in already_rows}

    agg: dict = {}
    per_contract: dict = {}
    for o in obligations:
        cents, through = already_map.get(o.id, (0, None))
        m = project_obligation_by_month(
            total_cents=o.total_amount_cents,
            start=o.start_date, end=o.end_date, pattern=o.pattern,
            already_cents=cents, already_through=through,
            today=today, horizon_months=months,
        )
        for k, v in m.items():
            agg[k] = agg.get(k, 0) + v
            per_contract.setdefault(str(o.contract_id), {})[str(k)] = \
                per_contract.setdefault(str(o.contract_id), {}).get(str(k), 0) + v

    total = sum(agg.values())
    month_keys = sorted(k for k in agg if k != BEYOND_KEY)
    n3 = sum(agg[k] for k in month_keys[:3])
    n12 = sum(agg[k] for k in month_keys[3:12])
    beyond = agg.get(BEYOND_KEY, 0) + sum(agg[k] for k in month_keys[12:])

    months_out = {str(k): v for k, v in agg.items()}
    data = {
        "months": months_out,
        "total": total,
        "buckets": {"next_3": n3, "months_4_to_12": n12, "beyond": beyond},
    }
    if _wants_json(request):
        return JSONResponse(data)
    return request.app.state.templates.TemplateResponse(
        request=request, name="revrec_waterfall.html",
        context={
            "total": total, "months": months_out, "buckets": data["buckets"],
            "per_contract": per_contract, "horizon_months": months,
        },
    )
