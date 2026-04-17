from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from finledger.db import SyncSessionLocal
from finledger.models.inbox import SourceEvent


router = APIRouter()


def get_session():
    with SyncSessionLocal() as s:
        yield s


@router.get("/", response_class=HTMLResponse)
def list_events(request: Request, session: Session = Depends(get_session)):
    rows = session.execute(
        select(SourceEvent).order_by(SourceEvent.received_at.desc()).limit(200)
    ).scalars().all()
    total = session.execute(select(func.count()).select_from(SourceEvent)).scalar_one()
    processed = session.execute(
        select(func.count()).select_from(SourceEvent).where(SourceEvent.processed_at.isnot(None))
    ).scalar_one()
    stuck_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    stuck = session.execute(
        select(func.count()).select_from(SourceEvent).where(
            SourceEvent.processed_at.is_(None), SourceEvent.received_at < stuck_cutoff
        )
    ).scalar_one()
    return request.app.state.templates.TemplateResponse(
        request=request, name="inbox_list.html",
        context={"rows": rows, "total": total, "processed": processed, "stuck": stuck},
    )
