from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from finledger.db import SyncSessionLocal
from finledger.models.recon import ReconRun


router = APIRouter()


def get_session():
    with SyncSessionLocal() as s:
        yield s


@router.get("/", response_class=HTMLResponse)
def list_runs(request: Request, session: Session = Depends(get_session)):
    runs = session.execute(
        select(ReconRun).order_by(ReconRun.started_at.desc()).limit(100)
    ).scalars().all()
    return request.app.state.templates.TemplateResponse(
        request=request, name="recon_list.html", context={"runs": runs},
    )
