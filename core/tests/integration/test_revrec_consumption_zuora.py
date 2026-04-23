import uuid
from datetime import date, datetime, timezone
from datetime import date as _date
import pytest
from sqlalchemy import select
from finledger.ingest.writer import insert_source_event
from finledger.models.revrec import (
    Contract, PerformanceObligation, UsageEvent,
)
from finledger.posting.engine import run_once as run_posting
from finledger.revrec.engine import run_recognition


async def _seed_consumption_obligation_with_external_ref(session, *, external_ref):
    contract = Contract(
        id=uuid.uuid4(), external_ref=f"C-{uuid.uuid4().hex[:8]}",
        effective_date=date(2026, 1, 1), status="active",
        total_amount_cents=10000, currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    session.add(contract)
    await session.flush()
    obligation = PerformanceObligation(
        id=uuid.uuid4(), contract_id=contract.id,
        description="Zuora usage test", pattern="consumption",
        start_date=date(2026, 1, 1), end_date=None,
        total_amount_cents=10000, currency="USD",
        units_total=1000, unit_label="calls",
        deferred_revenue_account_code="2000-DEFERRED-REV",
        revenue_account_code="4000-REV-SUB",
        external_ref=external_ref,
        created_at=datetime.now(timezone.utc),
    )
    session.add(obligation)
    await session.flush()
    return contract, obligation


@pytest.mark.asyncio
async def test_zuora_usage_webhook_matches_by_external_ref(session):
    _, obl = await _seed_consumption_obligation_with_external_ref(
        session, external_ref="rpc-abc123"
    )
    payload = {
        "eventType": "usage.uploaded",
        "ratePlanChargeId": "rpc-abc123",
        "quantity": 250,
        "startDateTime": "2026-03-10T00:00:00Z",
    }
    await insert_source_event(session, "zuora", "usage.uploaded", "zuora-evt-1", payload)
    await session.commit()

    posted = await run_posting(session)
    assert posted == 0

    events = (await session.execute(
        select(UsageEvent).where(UsageEvent.obligation_id == obl.id)
    )).scalars().all()
    assert len(events) == 1
    assert events[0].units == 250
    assert events[0].source == "zuora"


@pytest.mark.asyncio
async def test_zuora_usage_webhook_unmatched_external_ref_skips_cleanly(session):
    await _seed_consumption_obligation_with_external_ref(
        session, external_ref="rpc-known"
    )
    payload = {
        "eventType": "usage.uploaded",
        "ratePlanChargeId": "rpc-unknown",
        "quantity": 100,
        "startDateTime": "2026-03-10T00:00:00Z",
    }
    await insert_source_event(session, "zuora", "usage.uploaded", "zuora-evt-2", payload)
    await session.commit()

    await run_posting(session)
    events = (await session.execute(select(UsageEvent))).scalars().all()
    assert events == []


@pytest.mark.asyncio
async def test_zuora_usage_webhook_for_non_consumption_obligation_skips(session):
    contract = Contract(
        id=uuid.uuid4(), external_ref="C-RATABLE-Z",
        effective_date=date(2026, 1, 1), status="active",
        total_amount_cents=10000, currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    session.add(contract)
    await session.flush()
    ratable = PerformanceObligation(
        id=uuid.uuid4(), contract_id=contract.id,
        description="Ratable with external ref",
        pattern="ratable_daily",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
        total_amount_cents=10000, currency="USD",
        deferred_revenue_account_code="2000-DEFERRED-REV",
        revenue_account_code="4000-REV-SUB",
        external_ref="rpc-ratable",
        created_at=datetime.now(timezone.utc),
    )
    session.add(ratable)
    await session.flush()
    payload = {
        "eventType": "usage.uploaded",
        "ratePlanChargeId": "rpc-ratable",
        "quantity": 5,
        "startDateTime": "2026-03-10T00:00:00Z",
    }
    await insert_source_event(session, "zuora", "usage.uploaded", "zuora-evt-3", payload)
    await session.commit()

    await run_posting(session)
    events = (await session.execute(select(UsageEvent))).scalars().all()
    assert events == []


@pytest.mark.asyncio
async def test_zuora_usage_flows_through_to_recognition(session):
    _, obl = await _seed_consumption_obligation_with_external_ref(
        session, external_ref="rpc-e2e"
    )
    for i, qty in enumerate([100, 150, 250]):
        payload = {
            "eventType": "usage.uploaded",
            "ratePlanChargeId": "rpc-e2e",
            "quantity": qty,
            "startDateTime": "2026-03-10T00:00:00Z",
        }
        await insert_source_event(
            session, "zuora", "usage.uploaded", f"zuora-e2e-{i}", payload
        )
    await session.commit()
    await run_posting(session)

    events = (await session.execute(select(UsageEvent))).scalars().all()
    assert len(events) == 3
    assert all(ev.recognized_at is None for ev in events)

    run = await run_recognition(session, through_date=_date(2026, 5, 20))
    await session.commit()

    # Total units = 500, commitment = 1000 units / $100 → 50% drain = $50
    assert run.total_recognized_cents == 5000
    events = (await session.execute(select(UsageEvent))).scalars().all()
    assert all(ev.recognized_at is not None for ev in events)
    assert all(ev.recognition_run_id == run.id for ev in events)
