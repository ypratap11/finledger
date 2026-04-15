from hypothesis import strategies as st


@st.composite
def stripe_charge_payloads(draw):
    charge_id = draw(st.from_regex(r"ch_[a-z0-9]{10}", fullmatch=True))
    invoice_ref = draw(st.from_regex(r"I-[0-9]{4,6}", fullmatch=True))
    amount = draw(st.integers(min_value=1, max_value=1_000_000))
    return {
        "id": f"evt_{charge_id}",
        "type": "charge.succeeded",
        "data": {"object": {
            "id": charge_id, "amount": amount, "currency": "usd",
            "customer": "cus_test",
            "metadata": {"invoice_ref": invoice_ref},
        }},
    }


@st.composite
def zuora_invoice_payloads(draw):
    inv_id = draw(st.from_regex(r"INV-[0-9]{4,6}", fullmatch=True))
    inv_number = draw(st.from_regex(r"I-[0-9]{4,6}", fullmatch=True))
    amount = draw(st.integers(min_value=1, max_value=1_000_000))
    return {
        "eventType": "invoice.posted",
        "invoice": {
            "id": inv_id, "invoiceNumber": inv_number,
            "accountId": "ACC-TEST", "amount": amount, "currency": "USD",
        },
    }


def event_sequences():
    return st.lists(
        st.one_of(
            stripe_charge_payloads().map(lambda p: ("stripe", "charge.succeeded", p)),
            zuora_invoice_payloads().map(lambda p: ("zuora", "invoice.posted", p)),
        ),
        min_size=1, max_size=20,
    )
