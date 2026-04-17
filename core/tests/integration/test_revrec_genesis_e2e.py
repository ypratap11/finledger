import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from finledger.ingest.writer import insert_source_event
from finledger.models.revrec import Contract, PerformanceObligation
from finledger.revrec.genesis import from_zuora_invoice


@pytest.mark.asyncio
async def test_genesis_creates_contract_and_ratable_obligation(session):
    event = await insert_source_event(
        session, "zuora", "invoice.posted", "INV-TEST-1",
        {
            "eventType": "invoice.posted",
            "invoice": {
                "id": "INV-TEST-1",
                "invoiceNumber": "I-TEST-1",
                "accountId": "ACC-TEST",
                "amount": 120000,
                "currency": "USD",
                "metadata": {
                    "service_period_start": "2026-01-01",
                    "service_period_end": "2026-12-31",
                },
            },
        },
    )
    await session.commit()
    await from_zuora_invoice(session, event.payload, event.id)
    await session.commit()

    contract = (await session.execute(
        select(Contract).where(Contract.external_ref == "I-TEST-1")
    )).scalar_one()
    assert contract.total_amount_cents == 120000
    assert contract.customer_id == "ACC-TEST"
    assert contract.created_from_event_id == event.id

    obligations = (await session.execute(
        select(PerformanceObligation).where(PerformanceObligation.contract_id == contract.id)
    )).scalars().all()
    assert len(obligations) == 1
    assert obligations[0].pattern == "ratable_daily"
    assert obligations[0].total_amount_cents == 120000


@pytest.mark.asyncio
async def test_genesis_is_noop_without_service_period_metadata(session):
    event = await insert_source_event(
        session, "zuora", "invoice.posted", "INV-TEST-2",
        {
            "eventType": "invoice.posted",
            "invoice": {
                "id": "INV-TEST-2", "invoiceNumber": "I-TEST-2",
                "accountId": "ACC-TEST", "amount": 5000, "currency": "USD",
            },
        },
    )
    await session.commit()
    await from_zuora_invoice(session, event.payload, event.id)
    await session.commit()

    contracts = (await session.execute(select(Contract))).scalars().all()
    assert contracts == []


@pytest.mark.asyncio
async def test_genesis_is_idempotent_on_external_ref(session):
    payload = {
        "eventType": "invoice.posted",
        "invoice": {
            "id": "INV-TEST-3", "invoiceNumber": "I-TEST-3",
            "accountId": "ACC-TEST", "amount": 12000, "currency": "USD",
            "metadata": {"service_period_start": "2026-01-01",
                         "service_period_end": "2026-01-31"},
        },
    }
    event = await insert_source_event(session, "zuora", "invoice.posted", "INV-TEST-3", payload)
    await session.commit()
    await from_zuora_invoice(session, payload, event.id)
    await session.commit()
    await from_zuora_invoice(session, payload, event.id)
    await session.commit()

    contracts = (await session.execute(select(Contract))).scalars().all()
    assert len(contracts) == 1
