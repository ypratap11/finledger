import json
from datetime import date, datetime, timezone
from pathlib import Path
import pytest
from sqlalchemy import select
from finledger.ingest.writer import insert_source_event
from finledger.models.recon import ReconRun, ReconBreak
from finledger.posting.engine import run_once
from finledger.recon.stripe_ledger import StripeBalanceTx, run_stripe_ledger_recon


FIXTURES = Path(__file__).parents[2].parent / "fixtures"


@pytest.mark.asyncio
async def test_matched_charge(session):
    payload = json.loads((FIXTURES / "stripe_charge_succeeded.json").read_text())
    await insert_source_event(session, "stripe", "charge.succeeded", payload["id"], payload)
    await session.commit()
    await run_once(session)

    txs = [StripeBalanceTx(
        charge_id="ch_abc123", amount_cents=100000, currency="USD",
        created=datetime.now(timezone.utc),
    )]
    run = await run_stripe_ledger_recon(
        session, stripe_txs=txs, period_start=date.today(), period_end=date.today(),
    )
    await session.commit()
    assert run.matched_count == 1
    assert run.unmatched_count == 0
    assert run.mismatched_count == 0
    breaks = (await session.execute(select(ReconBreak).where(ReconBreak.run_id == run.id))).scalars().all()
    assert breaks == []


@pytest.mark.asyncio
async def test_amount_mismatch_produces_break(session):
    payload = json.loads((FIXTURES / "stripe_charge_succeeded.json").read_text())
    await insert_source_event(session, "stripe", "charge.succeeded", payload["id"], payload)
    await session.commit()
    await run_once(session)

    txs = [StripeBalanceTx(
        charge_id="ch_abc123", amount_cents=99999, currency="USD",
        created=datetime.now(timezone.utc),
    )]
    run = await run_stripe_ledger_recon(
        session, stripe_txs=txs, period_start=date.today(), period_end=date.today(),
    )
    await session.commit()
    assert run.mismatched_count == 1
    breaks = (await session.execute(select(ReconBreak).where(ReconBreak.run_id == run.id))).scalars().all()
    assert len(breaks) == 1
    assert breaks[0].kind == "amount_mismatch"


@pytest.mark.asyncio
async def test_stripe_only_charge_is_unmatched_external(session):
    txs = [StripeBalanceTx(
        charge_id="ch_ghost", amount_cents=500, currency="USD",
        created=datetime.now(timezone.utc),
    )]
    run = await run_stripe_ledger_recon(
        session, stripe_txs=txs, period_start=date.today(), period_end=date.today(),
    )
    await session.commit()
    assert run.unmatched_count == 1
    breaks = (await session.execute(select(ReconBreak).where(ReconBreak.run_id == run.id))).scalars().all()
    assert breaks[0].kind == "unmatched_external"
