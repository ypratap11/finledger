from collections import defaultdict
from datetime import date, timedelta
from calendar import monthrange

BEYOND_KEY = "beyond"


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _horizon_end(today: date, horizon_months: int) -> date:
    """First day of month horizon_months after today's month."""
    m = _month_start(today)
    for _ in range(horizon_months):
        m = _next_month(m)
    return m  # exclusive


def project_obligation_by_month(
    *, total_cents: int,
    start: date, end: date | None,
    pattern: str,
    already_cents: int,
    already_through: date | None,
    today: date,
    horizon_months: int,
) -> dict:
    """Return {month_start_date_or_BEYOND_KEY: cents} for unrecognized amounts."""
    out: dict = defaultdict(int)
    horizon = _horizon_end(today, horizon_months)

    if pattern == "point_in_time":
        if already_cents >= total_cents:
            return dict(out)
        recog_date = max(start, today)
        if recog_date >= horizon:
            out[BEYOND_KEY] += total_cents - already_cents
        else:
            out[_month_start(recog_date)] += total_cents - already_cents
        return dict(out)

    if pattern == "consumption":
        if already_cents >= total_cents:
            return dict(out)
        remaining = total_cents - already_cents
        out[_month_start(today)] += remaining
        return dict(out)

    if pattern == "consumption_payg":
        # No commitment to project; PAYG contributes nothing to the waterfall.
        return dict(out)

    if pattern == "ratable_daily":
        assert end is not None
        if already_cents >= total_cents:
            return dict(out)
        days_in_period = (end - start).days + 1
        daily = total_cents // days_in_period
        remainder = total_cents - (daily * days_in_period)

        candidates = [start, today]
        if already_through is not None:
            candidates.append(already_through + timedelta(days=1))
        cur = max(candidates)
        if cur > end:
            return dict(out)

        total_distributed = already_cents
        while cur <= end:
            month_key = _month_start(cur)
            month_last = min(
                end,
                date(cur.year, cur.month, monthrange(cur.year, cur.month)[1]),
            )
            days = (month_last - cur).days + 1
            amount = daily * days
            if month_last == end:
                amount += remainder
                remaining_to_recognize = total_cents - total_distributed
                if amount > remaining_to_recognize:
                    amount = remaining_to_recognize
            bucket = BEYOND_KEY if month_key >= horizon else month_key
            out[bucket] += amount
            total_distributed += amount
            cur = _next_month(month_last) if month_last != end else end + timedelta(days=1)
        return dict(out)

    raise ValueError(f"unknown pattern: {pattern}")
