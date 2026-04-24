"""Seed the dev database with a chart of accounts and two sample events.

Uses psycopg throughout (sync) to avoid Windows asyncpg networking issues.
Run after `alembic upgrade head`.
"""
import hashlib
import json
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://finledger:finledger@localhost:5432/finledger",
).replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
FIXTURES = Path(__file__).parent.parent / "fixtures"

CHART = [
    ("1000-CASH", "Cash", "asset", "debit"),
    ("1200-AR", "Accounts Receivable", "asset", "debit"),
    ("1500-UNBILLED-AR", "Unbilled Accounts Receivable / Contract Asset", "asset", "debit"),
    ("2000-DEFERRED-REV", "Deferred Revenue", "liability", "credit"),
    ("4000-REV-SUB", "Revenue - Subscription", "revenue", "credit"),
    ("4100-REV-USAGE", "Revenue - Usage", "revenue", "credit"),
]


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def row_hash(prev: bytes, source: str, ext: str, payload: bytes) -> bytes:
    h = hashlib.sha256()
    h.update(prev); h.update(source.encode()); h.update(b"\x00")
    h.update(ext.encode()); h.update(b"\x00"); h.update(payload)
    return h.digest()


def seed_accounts(cur):
    for code, name, t, side in CHART:
        cur.execute(
            "INSERT INTO ledger.accounts (id, code, name, type, normal_side) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (code) DO NOTHING",
            (uuid.uuid4(), code, name, t, side),
        )


def account_id(cur, code: str) -> uuid.UUID:
    cur.execute("SELECT id FROM ledger.accounts WHERE code = %s", (code,))
    return cur.fetchone()[0]


def insert_inbox(cur, source: str, event_type: str, external_id: str, payload: dict) -> uuid.UUID:
    cur.execute("SELECT row_hash FROM inbox.source_events ORDER BY received_at DESC, id DESC LIMIT 1")
    r = cur.fetchone()
    prev = bytes(r[0]) if r else b"\x00" * 32
    body = canonical(payload)
    rh = row_hash(prev, source, external_id, body)
    event_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO inbox.source_events "
        "(id, source, event_type, external_id, idempotency_key, payload, prev_hash, row_hash) "
        "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
        (event_id, source, event_type, external_id, f"{source}:{external_id}",
         json.dumps(payload), prev, rh),
    )
    return event_id


def post_stripe_charge(cur, event_id: uuid.UUID, payload: dict):
    obj = payload["data"]["object"]
    amt = int(obj["amount"])
    ccy = obj["currency"].upper()
    charge_id = obj["id"]
    invoice_ref = obj.get("metadata", {}).get("invoice_ref")
    entry_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO ledger.journal_entries (id, source_event_id, posted_at, status, memo) "
        "VALUES (%s, %s, now(), 'posted', %s)",
        (entry_id, event_id, f"stripe:charge.succeeded:{charge_id}"),
    )
    cash = account_id(cur, "1000-CASH")
    ar = account_id(cur, "1200-AR")
    cur.execute(
        "INSERT INTO ledger.journal_lines (id, entry_id, account_id, side, amount_cents, currency, external_ref, dimension_json) "
        "VALUES (%s, %s, %s, 'debit', %s, %s, %s, '{}'::jsonb)",
        (uuid.uuid4(), entry_id, cash, amt, ccy, charge_id),
    )
    cur.execute(
        "INSERT INTO ledger.journal_lines (id, entry_id, account_id, side, amount_cents, currency, external_ref, dimension_json) "
        "VALUES (%s, %s, %s, 'credit', %s, %s, %s, '{}'::jsonb)",
        (uuid.uuid4(), entry_id, ar, amt, ccy, invoice_ref),
    )
    cur.execute("UPDATE inbox.source_events SET processed_at = now() WHERE id = %s", (event_id,))


def post_zuora_invoice(cur, event_id: uuid.UUID, payload: dict):
    inv = payload["invoice"]
    amt = int(inv["amount"])
    ccy = inv["currency"].upper()
    inv_num = inv["invoiceNumber"]
    entry_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO ledger.journal_entries (id, source_event_id, posted_at, status, memo) "
        "VALUES (%s, %s, now(), 'posted', %s)",
        (entry_id, event_id, f"zuora:invoice.posted:{inv['id']}"),
    )
    ar = account_id(cur, "1200-AR")
    deferred = account_id(cur, "2000-DEFERRED-REV")
    cur.execute(
        "INSERT INTO ledger.journal_lines (id, entry_id, account_id, side, amount_cents, currency, external_ref, dimension_json) "
        "VALUES (%s, %s, %s, 'debit', %s, %s, %s, '{}'::jsonb)",
        (uuid.uuid4(), entry_id, ar, amt, ccy, inv_num),
    )
    cur.execute(
        "INSERT INTO ledger.journal_lines (id, entry_id, account_id, side, amount_cents, currency, external_ref, dimension_json) "
        "VALUES (%s, %s, %s, 'credit', %s, %s, %s, '{}'::jsonb)",
        (uuid.uuid4(), entry_id, deferred, amt, ccy, inv_num),
    )
    cur.execute("UPDATE inbox.source_events SET processed_at = now() WHERE id = %s", (event_id,))


def seed_recon(cur):
    run_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO recon.recon_runs "
        "(id, recon_type, period_start, period_end, started_at, finished_at, "
        "matched_count, unmatched_count, mismatched_count) "
        "VALUES (%s, 'stripe_ledger', %s, %s, now(), now(), 1, 1, 0)",
        (run_id, date.today(), date.today()),
    )
    cur.execute(
        "INSERT INTO recon.recon_breaks "
        "(id, run_id, kind, external_ref, ledger_amount_cents, details) "
        "VALUES (%s, %s, 'unmatched_ledger', 'I-1001', 100000, '{}'::jsonb)",
        (uuid.uuid4(), run_id),
    )


def main():
    stripe = json.loads((FIXTURES / "stripe_charge_succeeded.json").read_text())
    zuora = json.loads((FIXTURES / "zuora_invoice_posted.json").read_text())
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            seed_accounts(cur)  # already idempotent via ON CONFLICT
            cur.execute(
                "SELECT count(*) FROM inbox.source_events "
                "WHERE external_id IN (%s, %s)",
                (stripe["id"], zuora["invoice"]["id"]),
            )
            if cur.fetchone()[0] > 0:
                conn.commit()
                print("demo already seeded (events exist) — skipping")
                return
            e1 = insert_inbox(cur, "stripe", "charge.succeeded", stripe["id"], stripe)
            e2 = insert_inbox(cur, "zuora", "invoice.posted", zuora["invoice"]["id"], zuora)
            post_stripe_charge(cur, e1, stripe)
            post_zuora_invoice(cur, e2, zuora)
            seed_recon(cur)
        conn.commit()
    print("Seed complete: 2 events, 2 entries, 4 lines, 1 recon run (matched=1, unmatched=1)")


if __name__ == "__main__":
    main()
