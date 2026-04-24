import uuid
from datetime import date, datetime, timezone
import pytest
from sqlalchemy import select
from finledger.ingest.writer import insert_source_event
from finledger.models.ledger import JournalEntry, JournalLine, Account
from finledger.models.revrec import (
    Contract, PerformanceObligation, PaygReclassification,
)
from finledger.posting.engine import run_once as run_posting


async def _seed_payg_obligation(session, *, external_ref, deferred_account="2000-DEFERRED-REV"):
    contract = Contract(
        id=uuid.uuid4(), external_ref=f"C-{uuid.uuid4().hex[:8]}",
        effective_date=date(2026, 1, 1), status="active",
        total_amount_cents=1, currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    session.add(contract)
    await session.flush()
    obl = PerformanceObligation(
        id=uuid.uuid4(), contract_id=contract.id,
        description="PAYG", pattern="consumption_payg",
        start_date=date(2026, 1, 1), end_date=None,
        total_amount_cents=None, currency="USD",
        price_per_unit_cents=10,
        unit_label="API calls",
        external_ref=external_ref,
        deferred_revenue_account_code=deferred_account,
        revenue_account_code="4000-REV-SUB",
        unbilled_ar_account_code="1500-UNBILLED-AR",
        created_at=datetime.now(timezone.utc),
    )
    session.add(obl)
    await session.flush()
    return contract, obl


def _zuora_invoice_payload(*, invoice_number, amount_cents, payg_obligation_ref=None):
    invoice = {
        "id": invoice_number,
        "invoiceNumber": invoice_number,
        "accountId": "ACC-X",
        "amount": amount_cents,
        "currency": "USD",
        "metadata": {},
    }
    if payg_obligation_ref:
        invoice["metadata"]["payg_obligation_ref"] = payg_obligation_ref
    return {"eventType": "invoice.posted", "invoice": invoice}


@pytest.mark.asyncio
async def test_invoice_posted_for_payg_obligation_credits_unbilled_ar(session):
    _, obl = await _seed_payg_obligation(session, external_ref="payg-rpc-1")
    payload = _zuora_invoice_payload(
        invoice_number="I-PAYG-1", amount_cents=5000,
        payg_obligation_ref="payg-rpc-1",
    )
    await insert_source_event(session, "zuora", "invoice.posted", "evt-payg-1", payload)
    await session.commit()

    posted = await run_posting(session)
    assert posted == 1

    entries = (await session.execute(select(JournalEntry))).scalars().all()
    assert len(entries) == 1
    lines = (await session.execute(
        select(JournalLine, Account.code).join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == entries[0].id)
    )).all()
    by_code_side = {(code, line.side): line.amount_cents for line, code in lines}
    assert by_code_side[("1200-AR", "debit")] == 5000
    assert by_code_side[("1500-UNBILLED-AR", "credit")] == 5000
    # Verify NO deferred-rev credit for this PAYG invoice
    assert ("2000-DEFERRED-REV", "credit") not in by_code_side

    rec = (await session.execute(select(PaygReclassification))).scalar_one()
    assert rec.obligation_id == obl.id
    assert rec.amount_cents == 5000
    assert rec.invoice_external_ref == "I-PAYG-1"
    assert rec.journal_entry_id == entries[0].id


@pytest.mark.asyncio
async def test_invoice_posted_for_non_payg_obligation_unchanged(session):
    # Regular invoice (no payg_obligation_ref) — falls through to default DR AR / CR Deferred Rev
    payload = _zuora_invoice_payload(
        invoice_number="I-RATABLE-1", amount_cents=12000,
    )
    payload["invoice"]["metadata"] = {
        "service_period_start": "2026-01-01",
        "service_period_end": "2026-12-31",
    }
    await insert_source_event(session, "zuora", "invoice.posted", "evt-reg-1", payload)
    await session.commit()

    await run_posting(session)
    entries = (await session.execute(select(JournalEntry))).scalars().all()
    assert len(entries) == 1
    lines = (await session.execute(
        select(JournalLine, Account.code).join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == entries[0].id)
    )).all()
    by_code_side = {(code, line.side): line.amount_cents for line, code in lines}
    assert by_code_side[("1200-AR", "debit")] == 12000
    assert by_code_side[("2000-DEFERRED-REV", "credit")] == 12000
    assert ("1500-UNBILLED-AR", "credit") not in by_code_side
    assert (await session.execute(select(PaygReclassification))).scalars().all() == []


@pytest.mark.asyncio
async def test_invoice_with_unmatched_payg_ref_falls_through(session):
    # payg_obligation_ref points at an unknown rate plan charge id -> log info, skip rewrite
    payload = _zuora_invoice_payload(
        invoice_number="I-UNK-1", amount_cents=7000,
        payg_obligation_ref="rpc-does-not-exist",
    )
    await insert_source_event(session, "zuora", "invoice.posted", "evt-unk-1", payload)
    await session.commit()

    await run_posting(session)
    entries = (await session.execute(select(JournalEntry))).scalars().all()
    assert len(entries) == 1
    lines = (await session.execute(
        select(JournalLine, Account.code).join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == entries[0].id)
    )).all()
    by_code_side = {(code, line.side): line.amount_cents for line, code in lines}
    assert by_code_side[("2000-DEFERRED-REV", "credit")] == 7000
    assert (await session.execute(select(PaygReclassification))).scalars().all() == []


