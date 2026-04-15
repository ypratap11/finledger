from typing import Callable
from finledger.ledger.post import LineSpec
from finledger.posting.stripe_charge import map_charge_succeeded
from finledger.posting.zuora_invoice import map_invoice_posted


class UnknownEventType(Exception):
    pass


Mapper = Callable[[dict], list[LineSpec]]

DISPATCH: dict[tuple[str, str], Mapper] = {
    ("stripe", "charge.succeeded"): map_charge_succeeded,
    ("zuora", "invoice.posted"): map_invoice_posted,
}


def get_mapper(source: str, event_type: str) -> Mapper:
    try:
        return DISPATCH[(source, event_type)]
    except KeyError:
        raise UnknownEventType(f"no mapper for ({source}, {event_type})")
