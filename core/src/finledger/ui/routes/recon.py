from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.db import SessionLocal
from finledger.models.recon import ReconRun


router = APIRouter()


async def get_session():
    async with SessionLocal() as s:
        yield s


@router.get("/", response_class=HTMLResponse)
async def list_runs(request: Request, session: AsyncSession = Depends(get_session)):
    runs = (await session.execute(
        select(ReconRun).order_by(ReconRun.started_at.desc()).limit(100)
    )).scalars().all()
    return request.app.state.templates.TemplateResponse(
        request=request, name="recon_list.html", context={"runs": runs},
    )
