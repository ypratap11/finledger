from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from finledger.db import SessionLocal
from finledger.models.ledger import JournalEntry, JournalLine, Account


router = APIRouter()


async def get_session():
    async with SessionLocal() as s:
        yield s


@router.get("/", response_class=HTMLResponse)
async def list_entries(request: Request, session: AsyncSession = Depends(get_session)):
    entries = (await session.execute(
        select(JournalEntry).order_by(JournalEntry.posted_at.desc()).limit(200)
    )).scalars().all()
    return request.app.state.templates.TemplateResponse(
        request=request, name="journal_list.html", context={"entries": entries},
    )


@router.get("/{entry_id}", response_class=HTMLResponse)
async def entry_detail(entry_id: UUID, request: Request, session: AsyncSession = Depends(get_session)):
    entry = (await session.execute(select(JournalEntry).where(JournalEntry.id == entry_id))).scalar_one_or_none()
    if entry is None:
        raise HTTPException(404)
    line_rows = (await session.execute(
        select(JournalLine, Account.code).join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == entry_id)
    )).all()
    lines = [{
        "account_code": code,
        "side": l.side,
        "amount_cents": l.amount_cents,
        "currency": l.currency,
        "external_ref": l.external_ref,
    } for (l, code) in line_rows]
    return request.app.state.templates.TemplateResponse(
        request=request, name="journal_detail.html", context={"entry": entry, "lines": lines},
    )
