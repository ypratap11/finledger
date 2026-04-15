from finledger.ledger.post import LineSpec


def map_invoice_posted(payload: dict) -> list[LineSpec]:
    """Zuora invoice.posted -> DR AR, CR Deferred Revenue.

    Both lines carry the invoice number as external_ref so Zuora<->Ledger recon
    (M2) can match by invoice, and so Stripe-side AR credits match the same
    invoice_ref when payment arrives.
    """
    inv = payload["invoice"]
    invoice_number = inv["invoiceNumber"]
    amount_cents = int(inv["amount"])
    currency = inv["currency"].upper()
    account_id = inv.get("accountId")
    dims = {"customer_id": account_id} if account_id else {}

    return [
        LineSpec(
            account_code="1200-AR",
            side="debit",
            amount_cents=amount_cents,
            currency=currency,
            external_ref=invoice_number,
            dimension_json=dims,
        ),
        LineSpec(
            account_code="2000-DEFERRED-REV",
            side="credit",
            amount_cents=amount_cents,
            currency=currency,
            external_ref=invoice_number,
            dimension_json=dims,
        ),
    ]
