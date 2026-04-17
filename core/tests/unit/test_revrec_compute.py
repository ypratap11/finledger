from datetime import date
import pytest
from finledger.revrec.compute import (
    compute_recognition,
    ObligationSnapshot,
    RecognitionDelta,
)


def snap(total, start, end, pattern="ratable_daily"):
    return ObligationSnapshot(
        total_amount_cents=total,
        start_date=start,
        end_date=end,
        pattern=pattern,
    )


def test_ratable_before_start_returns_none():
    s = snap(36500, date(2026, 5, 1), date(2026, 5, 31))
    assert compute_recognition(s, 0, None, date(2026, 4, 30)) is None


def test_ratable_first_day_recognizes_one_day():
    s = snap(31000, date(2026, 5, 1), date(2026, 5, 31))  # 31 days exact
    d = compute_recognition(s, 0, None, date(2026, 5, 1))
    assert d is not None
    assert d.recognized_cents == 1000
    assert d.recognized_through == date(2026, 5, 1)


def test_ratable_full_period_at_end_date():
    s = snap(31000, date(2026, 5, 1), date(2026, 5, 31))
    d = compute_recognition(s, 0, None, date(2026, 5, 31))
    assert d.recognized_cents == 31000


def test_ratable_past_end_date_catches_up_to_total():
    s = snap(31000, date(2026, 5, 1), date(2026, 5, 31))
    d = compute_recognition(s, 0, None, date(2026, 6, 30))
    assert d.recognized_cents == 31000


def test_ratable_mid_period_from_scratch():
    s = snap(31000, date(2026, 5, 1), date(2026, 5, 31))
    d = compute_recognition(s, 0, None, date(2026, 5, 10))
    assert d.recognized_cents == 10 * 1000


def test_ratable_already_recognized_resume():
    s = snap(31000, date(2026, 5, 1), date(2026, 5, 31))
    d = compute_recognition(s, 5000, date(2026, 5, 5), date(2026, 5, 10))
    assert d.recognized_cents == 5 * 1000  # days 6-10
    assert d.recognized_through == date(2026, 5, 10)


def test_ratable_fully_recognized_returns_none():
    s = snap(31000, date(2026, 5, 1), date(2026, 5, 31))
    d = compute_recognition(s, 31000, date(2026, 5, 31), date(2026, 6, 1))
    assert d is None


def test_ratable_rounding_absorbs_on_last_day():
    # $100 / 7 days, daily_cents = 1428, remainder absorbed past end_date
    s = snap(10000, date(2026, 5, 1), date(2026, 5, 7))
    d_mid = compute_recognition(s, 0, None, date(2026, 5, 6))
    assert d_mid.recognized_cents == 1428 * 6
    d_end = compute_recognition(s, d_mid.recognized_cents, d_mid.recognized_through, date(2026, 5, 8))
    assert d_mid.recognized_cents + d_end.recognized_cents == 10000


def test_ratable_run_only_once_at_end_still_totals_correctly():
    s = snap(10000, date(2026, 5, 1), date(2026, 5, 7))
    d = compute_recognition(s, 0, None, date(2026, 5, 7))
    # days=7 * 1428 = 9996 (< 10000), returns 9996
    assert d.recognized_cents == 9996
    # A second run past end_date picks up the remainder
    d2 = compute_recognition(s, 9996, date(2026, 5, 7), date(2026, 5, 8))
    assert d2.recognized_cents == 4


def test_ratable_single_day_period():
    s = snap(5000, date(2026, 5, 1), date(2026, 5, 1))
    d = compute_recognition(s, 0, None, date(2026, 5, 1))
    assert d.recognized_cents == 5000


def test_point_in_time_before_start():
    s = snap(50000, date(2026, 5, 15), None, pattern="point_in_time")
    assert compute_recognition(s, 0, None, date(2026, 5, 14)) is None


def test_point_in_time_on_start_recognizes_full_amount():
    s = snap(50000, date(2026, 5, 15), None, pattern="point_in_time")
    d = compute_recognition(s, 0, None, date(2026, 5, 15))
    assert d.recognized_cents == 50000
    assert d.recognized_through == date(2026, 5, 15)


def test_point_in_time_already_recognized_returns_none():
    s = snap(50000, date(2026, 5, 15), None, pattern="point_in_time")
    assert compute_recognition(s, 50000, date(2026, 5, 15), date(2026, 5, 20)) is None


def test_unknown_pattern_raises():
    s = snap(1000, date(2026, 5, 1), date(2026, 5, 31), pattern="bogus")
    with pytest.raises(ValueError):
        compute_recognition(s, 0, None, date(2026, 5, 10))
