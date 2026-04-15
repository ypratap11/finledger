import json
from pathlib import Path
from finledger.posting.stripe_charge import map_charge_succeeded


FIXTURE = Path(__file__).parents[2].parent / "fixtures" / "stripe_charge_succeeded.json"


def test_charge_succeeded_produces_balanced_cash_ar_posting():
    payload = json.loads(FIXTURE.read_text())
    lines = map_charge_succeeded(payload)
    assert len(lines) == 2
    assert sum(l.amount_cents for l in lines if l.side == "debit") == \
        sum(l.amount_cents for l in lines if l.side == "credit")


def test_cash_line_carries_charge_id_as_external_ref():
    payload = json.loads(FIXTURE.read_text())
    lines = map_charge_succeeded(payload)
    cash = next(l for l in lines if l.account_code == "1000-CASH")
    assert cash.external_ref == "ch_abc123"
    assert cash.side == "debit"
    assert cash.amount_cents == 100000


def test_ar_line_carries_invoice_ref():
    payload = json.loads(FIXTURE.read_text())
    lines = map_charge_succeeded(payload)
    ar = next(l for l in lines if l.account_code == "1200-AR")
    assert ar.external_ref == "I-1001"
    assert ar.side == "credit"
    assert ar.amount_cents == 100000
