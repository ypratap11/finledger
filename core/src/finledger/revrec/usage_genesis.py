import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from finledger.models.revrec import PerformanceObligation, UsageEvent

log = logging.getLogger(__name__)


def _parse_datetime(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


async def from_zuora_usage(
    session: AsyncSession, payload: dict, source_event_id: uuid.UUID
) -> None:
    """Map a Zuora usage.uploaded webhook to a usage_events row.

    Skips (with INFO log) if required fields missing, obligation not found by
    external_ref, or obligation is not a consumption pattern.
    """
    rate_plan_charge_id = payload.get("ratePlanChargeId")
    quantity = payload.get("quantity")
    start_date = payload.get("startDateTime")
    if not (rate_plan_charge_id and quantity is not None and start_date):
        log.info("zuora usage event missing required fields; skipping")
        return
    try:
        units = int(quantity)
    except (TypeError, ValueError):
        log.info("zuora usage event has non-integer quantity; skipping")
        return
    if units <= 0:
        log.info("zuora usage event has non-positive quantity; skipping")
        return

    obligation = (await session.execute(
        select(PerformanceObligation).where(
            PerformanceObligation.external_ref == rate_plan_charge_id
        )
    )).scalar_one_or_none()
    if obligation is None:
        log.info(f"no obligation matches rate_plan_charge_id={rate_plan_charge_id!r}; skipping")
        return
    if obligation.pattern not in ("consumption", "consumption_payg"):
        log.warning(
            f"zuora usage event for obligation with pattern {obligation.pattern!r}, "
            f"not consumption-based; skipping"
        )
        return

    session.add(UsageEvent(
        id=uuid.uuid4(),
        obligation_id=obligation.id,
        units=units,
        occurred_at=_parse_datetime(start_date),
        received_at=datetime.now(timezone.utc),
        idempotency_key=f"zuora:{source_event_id}",
        source="zuora",
        source_event_id=source_event_id,
    ))
    await session.flush()
