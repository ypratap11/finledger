from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class ObligationSnapshot:
    """Minimum shape needed to compute recognition. Model-agnostic."""
    total_amount_cents: int
    start_date: date
    end_date: date | None
    pattern: str


@dataclass(frozen=True)
class RecognitionDelta:
    recognized_cents: int
    recognized_through: date


def compute_recognition(
    obligation: ObligationSnapshot,
    already_recognized_cents: int,
    already_recognized_through: date | None,
    run_through_date: date,
) -> RecognitionDelta | None:
    """Returns the amount to recognize between already_recognized_through (exclusive)
    and run_through_date (inclusive), or None if there's nothing to recognize."""
    if obligation.pattern == "point_in_time":
        return _compute_point_in_time(
            obligation, already_recognized_cents, run_through_date
        )
    if obligation.pattern == "ratable_daily":
        return _compute_ratable_daily(
            obligation, already_recognized_cents, already_recognized_through, run_through_date
        )
    raise ValueError(f"unknown pattern: {obligation.pattern}")


def _compute_ratable_daily(
    o: ObligationSnapshot,
    already_cents: int,
    already_through: date | None,
    d: date,
) -> RecognitionDelta | None:
    assert o.end_date is not None
    if d < o.start_date:
        return None
    if already_cents >= o.total_amount_cents:
        return None

    days_in_period = (o.end_date - o.start_date).days + 1
    daily_cents = o.total_amount_cents // days_in_period

    if d > o.end_date:
        remaining = o.total_amount_cents - already_cents
        if remaining <= 0:
            return None
        return RecognitionDelta(recognized_cents=remaining, recognized_through=o.end_date)

    if already_through is None or already_through < o.start_date:
        from_day = o.start_date
    else:
        from_day = already_through + timedelta(days=1)

    if from_day > d:
        return None

    days = (d - from_day).days + 1
    amount = daily_cents * days
    remaining = o.total_amount_cents - already_cents
    if amount > remaining:
        amount = remaining
    if amount <= 0:
        return None
    return RecognitionDelta(recognized_cents=amount, recognized_through=d)


def _compute_point_in_time(
    o: ObligationSnapshot,
    already_cents: int,
    d: date,
) -> RecognitionDelta | None:
    if d < o.start_date:
        return None
    if already_cents >= o.total_amount_cents:
        return None
    return RecognitionDelta(
        recognized_cents=o.total_amount_cents - already_cents,
        recognized_through=o.start_date,
    )
