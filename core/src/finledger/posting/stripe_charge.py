from finledger.ledger.post import LineSpec


def map_charge_succeeded(payload: dict) -> list[LineSpec]:
    """Stripe charge.succeeded -> DR Cash, CR AR.

    The cash line carries the Stripe charge ID (for Stripe<->Ledger recon).
    The AR line carries the invoice ref from metadata (for Zuora<->Ledger recon in M2).
    """
    obj = payload["data"]["object"]
    charge_id = obj["id"]
    amount_cents = int(obj["amount"])
    currency = obj["currency"].upper()
    invoice_ref = obj.get("metadata", {}).get("invoice_ref")
    customer = obj.get("customer")

    dims = {"customer_id": customer} if customer else {}

    return [
        LineSpec(
            account_code="1000-CASH",
            side="debit",
            amount_cents=amount_cents,
            currency=currency,
            external_ref=charge_id,
            dimension_json=dims,
        ),
        LineSpec(
            account_code="1200-AR",
            side="credit",
            amount_cents=amount_cents,
            currency=currency,
            external_ref=invoice_ref,
            dimension_json=dims,
        ),
    ]
