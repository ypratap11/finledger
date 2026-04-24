import uuid
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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
    units_total: int | None = None
    unit_label: str | None = None
    external_ref: str | None = None


class ObligationOut(BaseModel):
    id: UUID


@router.get("/contracts/{contract_id}")
async def contract_detail(
    contract_id: UUID, request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    from finledger.models.revrec import RecognitionEvent

    contract = (await session.execute(
        select(Contract).where(Contract.id == contract_id)
    )).scalar_one_or_none()
    if contract is None:
        raise HTTPException(404)
    obligations = (await session.execute(
        select(PerformanceObligation).where(PerformanceObligation.contract_id == contract_id)
    )).scalars().all()

    rec_rows = (await session.execute(
        select(
            RecognitionEvent.obligation_id,
            func.coalesce(func.sum(RecognitionEvent.recognized_cents), 0),
        ).where(RecognitionEvent.obligation_id.in_([o.id for o in obligations]))
        .group_by(RecognitionEvent.obligation_id)
    )).all()
    recognized_map = {oid: int(cents) for oid, cents in rec_rows}

    from finledger.models.revrec import UsageEvent
    consumption_ids = [o.id for o in obligations if o.pattern == "consumption"]
    units_by_obligation: dict = {}
    recent_events_by_obligation: dict = {}
    if consumption_ids:
        unit_rows = (await session.execute(
            select(
                UsageEvent.obligation_id,
                func.coalesce(func.sum(UsageEvent.units), 0),
            )
            .where(UsageEvent.obligation_id.in_(consumption_ids))
            .group_by(UsageEvent.obligation_id)
        )).all()
        units_by_obligation = {oid: int(n) for oid, n in unit_rows}
        for oid in consumption_ids:
            recent = (await session.execute(
                select(UsageEvent)
                .where(UsageEvent.obligation_id == oid)
                .order_by(UsageEvent.received_at.desc())
                .limit(5)
            )).scalars().all()
            recent_events_by_obligation[oid] = recent

    obl_views = []
    for o in obligations:
        recognized = recognized_map.get(o.id, 0)
        pct = int(100 * recognized / o.total_amount_cents) if o.total_amount_cents else 0
        units_consumed = units_by_obligation.get(o.id, 0)
        units_pct = (
            int(100 * units_consumed / o.units_total)
            if (o.pattern == "consumption" and o.units_total)
            else 0
        )
        obl_views.append({
            "obligation": o,
            "recognized": recognized,
            "deferred": o.total_amount_cents - recognized,
            "pct": pct,
            "units_consumed": units_consumed,
            "units_pct": units_pct,
            "recent_events": recent_events_by_obligation.get(o.id, []),
        })

    return request.app.state.templates.TemplateResponse(
        request=request, name="revrec_contract_detail.html",
        context={"contract": contract, "obligations": obl_views},
    )


@router.post("/contracts/{contract_id}/obligations", status_code=201, response_model=ObligationOut)
async def create_obligation(
    contract_id: UUID, body: ObligationIn,
    session: AsyncSession = Depends(get_async_session),
):
    if body.pattern == "ratable_daily" and body.end_date is None:
        raise HTTPException(422, "ratable_daily requires end_date")
    if body.pattern not in ("ratable_daily", "point_in_time", "consumption"):
        raise HTTPException(422, f"unknown pattern: {body.pattern}")
    if body.end_date is not None and body.end_date < body.start_date:
        raise HTTPException(422, "end_date before start_date")
    if body.pattern == "consumption":
        if body.units_total is None or body.units_total <= 0:
            raise HTTPException(422, "consumption pattern requires positive units_total")
    else:
        if body.units_total is not None:
            raise HTTPException(422, f"units_total only valid for consumption pattern, got {body.pattern}")

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
        units_total=body.units_total,
        unit_label=body.unit_label,
        external_ref=body.external_ref,
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

    contract_refs = dict((await session.execute(
        select(Contract.id, Contract.external_ref)
    )).all())

    already_rows = (await session.execute(
        select(
            RecognitionEvent.obligation_id,
            func.coalesce(func.sum(RecognitionEvent.recognized_cents), 0),
            func.max(RecognitionEvent.recognized_through),
        ).group_by(RecognitionEvent.obligation_id)
    )).all()
    already_map = {oid: (int(cents), through) for oid, cents, through in already_rows}

    agg: dict = {}
    per_contract: dict = {}  # contract_id -> {month_key_str: cents}
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
            per_contract.setdefault(o.contract_id, {})[str(k)] = \
                per_contract.setdefault(o.contract_id, {}).get(str(k), 0) + v

    total = sum(agg.values())
    month_keys_sorted = sorted(k for k in agg if k != BEYOND_KEY)
    n3 = sum(agg[k] for k in month_keys_sorted[:3])
    n12 = sum(agg[k] for k in month_keys_sorted[3:12])
    beyond = agg.get(BEYOND_KEY, 0) + sum(agg[k] for k in month_keys_sorted[12:])

    # Stable ordered column list: months asc, then beyond
    ordered_columns = [str(k) for k in month_keys_sorted] + [BEYOND_KEY]
    total_row = [agg.get(k, 0) for k in month_keys_sorted] + [agg.get(BEYOND_KEY, 0)]

    # Contract rows, sorted by total descending
    contract_rows = []
    for cid, months_map in per_contract.items():
        cells = [months_map.get(str(k), 0) for k in month_keys_sorted] + [months_map.get(BEYOND_KEY, 0)]
        contract_rows.append({
            "external_ref": contract_refs.get(cid, str(cid)),
            "contract_id": str(cid),
            "total": sum(cells),
            "cells": cells,
        })
    contract_rows.sort(key=lambda r: -r["total"])

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
            "total": total,
            "buckets": data["buckets"],
            "horizon_months": months,
            "columns": ordered_columns,
            "total_row": total_row,
            "contract_rows": contract_rows,
        },
    )


@router.get("")
@router.get("/")
async def revrec_index(request: Request, session: AsyncSession = Depends(get_async_session)):
    return await waterfall(request=request, months=12, session=session)


# ---- M2a-1.5a: usage events --------------------------------------------------


class UsageIn(BaseModel):
    obligation_id: UUID
    units: int
    occurred_at: datetime
    idempotency_key: str


class UsageOut(BaseModel):
    id: UUID
    received_at: datetime


@router.post("/usage", status_code=201, response_model=UsageOut)
async def post_usage(
    body: UsageIn,
    session: AsyncSession = Depends(get_async_session),
):
    from finledger.models.revrec import UsageEvent
    if body.units <= 0:
        raise HTTPException(422, "units must be > 0")
    now = datetime.now(timezone.utc)
    occurred = body.occurred_at
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    if occurred > now + timedelta(minutes=5):
        raise HTTPException(422, "occurred_at in the future")

    obligation = (await session.execute(
        select(PerformanceObligation).where(PerformanceObligation.id == body.obligation_id)
    )).scalar_one_or_none()
    if obligation is None:
        raise HTTPException(404, "obligation not found")
    if obligation.pattern != "consumption":
        raise HTTPException(422, f"obligation pattern is {obligation.pattern!r}, not 'consumption'")

    ev = UsageEvent(
        id=uuid.uuid4(),
        obligation_id=body.obligation_id,
        units=body.units,
        occurred_at=occurred,
        received_at=now,
        idempotency_key=body.idempotency_key,
        source="api",
    )
    session.add(ev)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        if "idempotency_key" in str(e.orig):
            raise HTTPException(409, "duplicate idempotency_key")
        raise
    return UsageOut(id=ev.id, received_at=ev.received_at)


@router.get("/usage")
async def list_usage(
    request: Request,
    obligation_id: UUID | None = None,
    session: AsyncSession = Depends(get_async_session),
):
    from finledger.models.revrec import UsageEvent
    q = select(UsageEvent).order_by(UsageEvent.received_at.desc()).limit(500)
    if obligation_id is not None:
        q = q.where(UsageEvent.obligation_id == obligation_id)
    rows = (await session.execute(q)).scalars().all()
    data = {
        "events": [
            {
                "id": str(e.id),
                "obligation_id": str(e.obligation_id),
                "units": e.units,
                "occurred_at": e.occurred_at.isoformat(),
                "received_at": e.received_at.isoformat(),
                "source": e.source,
                "recognized_at": e.recognized_at.isoformat() if e.recognized_at else None,
                "recognition_run_id": str(e.recognition_run_id) if e.recognition_run_id else None,
            }
            for e in rows
        ]
    }
    if _wants_json(request):
        return JSONResponse(data)
    return request.app.state.templates.TemplateResponse(
        request=request, name="revrec_usage.html",
        context={"events": rows},
    )
