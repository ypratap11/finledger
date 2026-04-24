import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.ledger.post import LineSpec, post_entry
from finledger.models.revrec import (
    PerformanceObligation, RecognitionEvent, RecognitionRun, UsageEvent,
)
from finledger.revrec.compute import ObligationSnapshot, compute_recognition


async def _existing_completed_run(session: AsyncSession, through: date) -> RecognitionRun | None:
    result = await session.execute(
        select(RecognitionRun)
        .where(RecognitionRun.finished_at.isnot(None))
        .where(RecognitionRun.run_through_date >= through)
        .order_by(RecognitionRun.run_through_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _obligation_state(session: AsyncSession, obligation_id: uuid.UUID) -> tuple[int, date | None]:
    row = (await session.execute(
        select(
            func.coalesce(func.sum(RecognitionEvent.recognized_cents), 0),
            func.max(RecognitionEvent.recognized_through),
        ).where(RecognitionEvent.obligation_id == obligation_id)
    )).one()
    return int(row[0]), row[1]


async def _pending_usage_for(
    session: AsyncSession, obligation_id: uuid.UUID
) -> tuple[int, list[uuid.UUID]]:
    """Return (sum of pending units, list of event ids) for an obligation."""
    rows = (await session.execute(
        select(UsageEvent.id, UsageEvent.units)
        .where(UsageEvent.obligation_id == obligation_id)
        .where(UsageEvent.recognized_at.is_(None))
    )).all()
    total_units = sum(int(units) for _id, units in rows)
    ids = [rid for rid, _ in rows]
    return total_units, ids


async def run_recognition(session: AsyncSession, *, through_date: date) -> RecognitionRun:
    """Compute and post recognition deltas for all active obligations through `through_date`.

    Idempotent: if a completed run already exists for >= through_date, returns that run.
    """
    existing = await _existing_completed_run(session, through_date)
    if existing is not None:
        return existing

    run = RecognitionRun(
        id=uuid.uuid4(),
        run_through_date=through_date,
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    await session.flush()

    obligations = (await session.execute(
        select(PerformanceObligation).join(PerformanceObligation.contract)
        .where(PerformanceObligation.contract.has(status="active"))
        .where(PerformanceObligation.start_date <= through_date)
    )).scalars().all()

    lines_agg: dict[tuple[str, str], int] = defaultdict(int)
    events: list[RecognitionEvent] = []
    obligations_processed = 0
    total = 0
    picked_up_event_ids: list[uuid.UUID] = []

    for o in obligations:
        already_cents, already_through = await _obligation_state(session, o.id)
        unprocessed_units = 0
        obl_event_ids: list[uuid.UUID] = []
        if o.pattern in ("consumption", "consumption_payg"):
            unprocessed_units, obl_event_ids = await _pending_usage_for(session, o.id)
        snap = ObligationSnapshot(
            total_amount_cents=o.total_amount_cents,
            start_date=o.start_date,
            end_date=o.end_date,
            pattern=o.pattern,
            units_total=o.units_total,
            price_per_unit_cents=o.price_per_unit_cents,
        )
        delta = compute_recognition(
            snap, already_cents, already_through, through_date,
            unprocessed_units=unprocessed_units,
        )
        if delta is None:
            # Mark pending events processed even on a no-op so they aren't re-queued.
            if o.pattern in ("consumption", "consumption_payg") and obl_event_ids:
                picked_up_event_ids.extend(obl_event_ids)
            continue
        debit_account = (
            o.unbilled_ar_account_code
            if o.pattern == "consumption_payg"
            else o.deferred_revenue_account_code
        )
        lines_agg[(debit_account, "debit")] += delta.recognized_cents
        lines_agg[(o.revenue_account_code, "credit")] += delta.recognized_cents
        events.append(RecognitionEvent(
            id=uuid.uuid4(),
            run_id=run.id,
            obligation_id=o.id,
            recognized_cents=delta.recognized_cents,
            recognized_through=delta.recognized_through,
        ))
        obligations_processed += 1
        total += delta.recognized_cents
        if o.pattern in ("consumption", "consumption_payg"):
            picked_up_event_ids.extend(obl_event_ids)

    if obligations_processed > 0:
        lines = [
            LineSpec(account_code=code, side=side, amount_cents=amt, currency="USD")
            for (code, side), amt in lines_agg.items()
        ]
        entry = await post_entry(
            session,
            lines=lines,
            memo=f"revrec:run:{through_date.isoformat()}",
        )
        run.journal_entry_id = entry.id
        for e in events:
            session.add(e)

    if picked_up_event_ids:
        await session.execute(
            update(UsageEvent)
            .where(UsageEvent.id.in_(picked_up_event_ids))
            .values(recognized_at=datetime.now(timezone.utc), recognition_run_id=run.id)
        )

    run.obligations_processed = obligations_processed
    run.total_recognized_cents = total
    run.finished_at = datetime.now(timezone.utc)
    await session.flush()
    return run
