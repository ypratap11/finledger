import json
import os
import time
from pathlib import Path
import hmac
import hashlib
import httpx
import pytest
from sqlalchemy import select
from finledger.models.inbox import SourceEvent
from finledger.models.ledger import JournalEntry
from finledger.posting.engine import run_once


FIXTURES = Path(__file__).parents[2].parent / "fixtures"
INGEST_URL = os.getenv("INGEST_URL", "http://localhost:3001")


def _stripe_signature(body: str, secret: str) -> str:
    ts = int(time.time())
    signed = f"{ts}.{body}".encode()
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


@pytest.mark.asyncio
async def test_stripe_webhook_flows_to_journal(session):
    """Requires ingest-edge running on localhost:3001 with STRIPE_WEBHOOK_SECRET=whsec_test."""
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    payload = json.loads((FIXTURES / "stripe_charge_succeeded.json").read_text())
    body = json.dumps(payload)
    sig = _stripe_signature(body, secret)

    try:
        r = httpx.post(f"{INGEST_URL}/webhooks/stripe", content=body,
                       headers={"stripe-signature": sig, "content-type": "application/json"})
    except httpx.ConnectError:
        pytest.skip("ingest-edge not running on localhost:3001")

    assert r.status_code == 200, r.text

    rows = (await session.execute(select(SourceEvent).where(SourceEvent.source == "stripe"))).scalars().all()
    assert len(rows) == 1

    await run_once(session)

    entries = (await session.execute(select(JournalEntry))).scalars().all()
    assert len(entries) == 1
