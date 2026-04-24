from datetime import date
from finledger.revrec.waterfall import project_obligation_by_month


def test_ratable_spans_two_months_full_allocation():
    months = project_obligation_by_month(
        total_cents=31000, start=date(2026, 5, 1), end=date(2026, 5, 31),
        pattern="ratable_daily", already_cents=10000, already_through=date(2026, 5, 10),
        today=date(2026, 5, 10), horizon_months=3,
    )
    assert months[date(2026, 5, 1)] == 21000
    assert months.get(date(2026, 6, 1), 0) == 0


def test_ratable_spans_13_months_hits_beyond_bucket():
    from finledger.revrec.waterfall import BEYOND_KEY
    months = project_obligation_by_month(
        total_cents=12 * 30 * 1000,
        start=date(2026, 1, 1), end=date(2027, 1, 31),
        pattern="ratable_daily",
        already_cents=0, already_through=None,
        today=date(2026, 4, 16), horizon_months=12,
    )
    assert BEYOND_KEY in months or date(2027, 1, 1) in months


def test_point_in_time_future_lands_in_start_month():
    months = project_obligation_by_month(
        total_cents=50000, start=date(2026, 8, 15), end=None,
        pattern="point_in_time",
        already_cents=0, already_through=None,
        today=date(2026, 4, 16), horizon_months=12,
    )
    assert months[date(2026, 8, 1)] == 50000


def test_point_in_time_past_start_already_recognized_is_empty():
    months = project_obligation_by_month(
        total_cents=50000, start=date(2026, 3, 15), end=None,
        pattern="point_in_time",
        already_cents=50000, already_through=date(2026, 3, 15),
        today=date(2026, 4, 16), horizon_months=12,
    )
    assert sum(months.values()) == 0


def test_consumption_remaining_collapses_to_today_month():
    months = project_obligation_by_month(
        total_cents=100000, start=date(2026, 1, 1), end=None,
        pattern="consumption",
        already_cents=60000, already_through=None,
        today=date(2026, 5, 15), horizon_months=12,
    )
    assert months[date(2026, 5, 1)] == 40000
    assert len([k for k, v in months.items() if v > 0]) == 1


def test_consumption_fully_recognized_returns_empty():
    months = project_obligation_by_month(
        total_cents=100000, start=date(2026, 1, 1), end=None,
        pattern="consumption",
        already_cents=100000, already_through=None,
        today=date(2026, 5, 15), horizon_months=12,
    )
    assert sum(months.values()) == 0


def test_consumption_payg_contributes_nothing():
    months = project_obligation_by_month(
        total_cents=0, start=date(2026, 1, 1), end=None,
        pattern="consumption_payg",
        already_cents=5000, already_through=None,
        today=date(2026, 5, 15), horizon_months=12,
    )
    assert sum(months.values()) == 0
