from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from finledger.db import SyncSessionLocal
from finledger.models.inbox import SourceEvent
from finledger.models.ledger import JournalEntry, JournalLine
from finledger.models.recon import ReconRun


router = APIRouter()


def get_session():
    with SyncSessionLocal() as s:
        yield s


@router.get("/", response_class=HTMLResponse)
def flow_overview(request: Request, session: Session = Depends(get_session)):
    total_events = session.execute(select(func.count()).select_from(SourceEvent)).scalar_one()
    processed = session.execute(
        select(func.count()).select_from(SourceEvent).where(SourceEvent.processed_at.isnot(None))
    ).scalar_one()
    pending = session.execute(
        select(func.count()).select_from(SourceEvent).where(
            SourceEvent.processed_at.is_(None), SourceEvent.processing_error.is_(None)
        )
    ).scalar_one()
    errored = session.execute(
        select(func.count()).select_from(SourceEvent).where(SourceEvent.processing_error.isnot(None))
    ).scalar_one()
    entries = session.execute(select(func.count()).select_from(JournalEntry)).scalar_one()
    lines = session.execute(select(func.count()).select_from(JournalLine)).scalar_one()
    recon_runs = session.execute(select(func.count()).select_from(ReconRun)).scalar_one()
    total_matched = session.execute(select(func.coalesce(func.sum(ReconRun.matched_count), 0))).scalar_one()
    total_breaks = session.execute(select(
        func.coalesce(func.sum(ReconRun.unmatched_count), 0) + func.coalesce(func.sum(ReconRun.mismatched_count), 0)
    )).scalar_one()

    recent = session.execute(
        select(
            SourceEvent.received_at,
            SourceEvent.source,
            SourceEvent.event_type,
            SourceEvent.external_id,
            SourceEvent.processed_at,
            SourceEvent.processing_error,
        )
        .order_by(SourceEvent.received_at.desc())
        .limit(10)
    ).all()

    activity = []
    for row in recent:
        if row.processing_error:
            status = "error"
            stage = "Posting Engine"
        elif row.processed_at:
            status = "ok"
            stage = "Journal"
        else:
            status = "pending"
            stage = "Inbox"
        activity.append({
            "received_at": row.received_at,
            "source": row.source,
            "event_type": row.event_type,
            "external_id": row.external_id,
            "status": status,
            "stage": stage,
            "latency": f"{(row.processed_at - row.received_at).total_seconds():.1f}s" if row.processed_at else "-",
        })

    return request.app.state.templates.TemplateResponse(
        request=request, name="flow.html",
        context={
            "total_events": total_events,
            "processed": processed,
            "pending": pending,
            "errored": errored,
            "entries": entries,
            "lines": lines,
            "recon_runs": recon_runs,
            "total_matched": total_matched,
            "total_breaks": total_breaks,
            "activity": activity,
        },
    )
