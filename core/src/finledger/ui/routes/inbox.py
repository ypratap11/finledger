from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone, timedelta
from finledger.db import SessionLocal
from finledger.models.inbox import SourceEvent


router = APIRouter()


async def get_session():
    async with SessionLocal() as s:
        yield s


@router.get("/", response_class=HTMLResponse)
async def list_events(request: Request, session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(
        select(SourceEvent).order_by(SourceEvent.received_at.desc()).limit(200)
    )).scalars().all()
    total = (await session.execute(select(func.count()).select_from(SourceEvent))).scalar_one()
    processed = (await session.execute(
        select(func.count()).select_from(SourceEvent).where(SourceEvent.processed_at.isnot(None))
    )).scalar_one()
    stuck_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    stuck = (await session.execute(
        select(func.count()).select_from(SourceEvent).where(
            SourceEvent.processed_at.is_(None), SourceEvent.received_at < stuck_cutoff
        )
    )).scalar_one()
    return request.app.state.templates.TemplateResponse(
        request=request, name="inbox_list.html",
        context={"rows": rows, "total": total, "processed": processed, "stuck": stuck},
    )
