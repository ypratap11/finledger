import csv
import hashlib
import json
from datetime import date
from pathlib import Path
import pytest
from sqlalchemy import text
from finledger.export.base import DateRange
from finledger.export.csv_exporter import CsvJournalExporter
from finledger.ingest.writer import insert_source_event
from finledger.posting.engine import run_once


FIXTURES = Path(__file__).parents[2].parent / "fixtures"


@pytest.mark.asyncio
async def test_empty_period_writes_header_only(session, tmp_path):
    exp = CsvJournalExporter(session)
    result = await exp.export(DateRange(date(2020, 1, 1), date(2020, 1, 31)), tmp_path)
    await session.commit()
    assert result.entries_exported == 0

    with result.file_path.open() as f:
        rows = list(csv.reader(f))
    assert len(rows) == 1
    assert rows[0][0] == "posting_date"


@pytest.mark.asyncio
async def test_stripe_charge_exports_balanced_rows(session, tmp_path):
    payload = json.loads((FIXTURES / "stripe_charge_succeeded.json").read_text())
    await insert_source_event(session, "stripe", "charge.succeeded", payload["id"], payload)
    await session.commit()
    await run_once(session)

    today = date.today()
    exp = CsvJournalExporter(session)
    result = await exp.export(DateRange(today, today), tmp_path)
    await session.commit()

    with result.file_path.open() as f:
        rows = list(csv.DictReader(f))

    # One row per (date, account_code, currency). Stripe posting hits CASH and AR.
    assert len(rows) == 2
    total_debit = sum(int(r["debit"]) for r in rows)
    total_credit = sum(int(r["credit"]) for r in rows)
    assert total_debit == total_credit == 100000
    assert result.entries_exported == 2
    assert result.checksum == hashlib.sha256(result.file_path.read_bytes()).hexdigest()

    # Persisted in gl.export_runs
    run = (await session.execute(
        text("SELECT checksum, entries_count FROM gl.export_runs WHERE id = :id"),
        {"id": result.run_id},
    )).first()
    assert run.checksum == result.checksum
    assert run.entries_count == 2

    # source_refs column contains the inbox external_id
    cash_row = next(r for r in rows if r["account_code"] == "1000-CASH")
    assert "evt_stripe_1" in cash_row["source_refs"]


@pytest.mark.asyncio
async def test_source_refs_truncated_at_limit(session, tmp_path):
    # Seed many charges on the same date, same account, so their refs aggregate.
    for i in range(300):
        payload = {
            "id": f"evt_x{i}",
            "type": "charge.succeeded",
            "data": {"object": {
                "id": f"ch_{i:04d}", "amount": 1000, "currency": "usd",
                "customer": "cus_x", "metadata": {"invoice_ref": f"I-{i}"},
            }},
        }
        await insert_source_event(session, "stripe", "charge.succeeded", payload["id"], payload)
    await session.commit()
    while await run_once(session, limit=500):
        pass

    today = date.today()
    exp = CsvJournalExporter(session)
    result = await exp.export(DateRange(today, today), tmp_path)
    await session.commit()

    with result.file_path.open() as f:
        rows = list(csv.DictReader(f))

    cash = next(r for r in rows if r["account_code"] == "1000-CASH")
    assert len(cash["source_refs"]) <= 1024
    assert cash["source_refs"].endswith("...")
