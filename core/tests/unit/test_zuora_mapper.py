import json
from pathlib import Path
from finledger.posting.zuora_invoice import map_invoice_posted


FIXTURE = Path(__file__).parents[2].parent / "fixtures" / "zuora_invoice_posted.json"


def test_invoice_posted_produces_ar_and_deferred_revenue():
    payload = json.loads(FIXTURE.read_text())
    lines = map_invoice_posted(payload)
    assert len(lines) == 2
    by_account = {l.account_code: l for l in lines}
    assert by_account["1200-AR"].side == "debit"
    assert by_account["2000-DEFERRED-REV"].side == "credit"
    assert by_account["1200-AR"].amount_cents == 100000
    assert by_account["2000-DEFERRED-REV"].amount_cents == 100000


def test_both_lines_carry_invoice_number_as_external_ref():
    payload = json.loads(FIXTURE.read_text())
    lines = map_invoice_posted(payload)
    for l in lines:
        assert l.external_ref == "I-1001"
