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
