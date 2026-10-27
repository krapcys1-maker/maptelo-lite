"""Working days: Saturdays, Sundays and Poland's public holidays are skipped (the NBP rate of a
tax point is the one of the last working day before it)."""

from __future__ import annotations

from datetime import date

import pytest

from maptelo.model.schema import DayShift
from maptelo.workdays import holidays, shift, working


@pytest.mark.parametrize(
    ("year", "easter"),
    [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5))],
)
def test_easter_and_the_holidays_that_move_with_it(year: int, easter: date) -> None:
    days = holidays("PL", year)
    assert easter in days
    assert date.fromordinal(easter.toordinal() + 1) in days  # Easter Monday
    assert date.fromordinal(easter.toordinal() + 60) in days  # Corpus Christi


def test_christmas_eve_is_free_from_2025() -> None:
    assert date(2024, 12, 24) not in holidays("PL", 2024)
    assert date(2025, 12, 24) in holidays("PL", 2025)


def test_the_last_working_day_before() -> None:
    assert shift(date(2026, 9, 16), -1, "PL") == date(2026, 9, 15)  # a Wednesday: Tuesday
    assert shift(date(2026, 9, 21), -1, "PL") == date(2026, 9, 18)  # a Monday: Friday
    assert shift(date(2026, 11, 12), -1, "PL") == date(2026, 11, 10)  # after 11 November
    assert shift(date(2026, 4, 7), -1, "PL") == date(2026, 4, 3)  # after Easter Monday
    assert shift(date(2026, 11, 12), -1, None) == date(2026, 11, 11)  # weekends only


def test_counted_forward_and_on_any_day() -> None:
    assert shift(date(2026, 9, 18), 1, "PL") == date(2026, 9, 21)
    assert shift(date(2026, 9, 19), -1, "PL") == date(2026, 9, 18)  # from a Saturday
    assert not working(date(2026, 5, 3), "PL")


def test_a_shift_in_working_days_in_the_model() -> None:
    rule = DayShift.model_validate(
        {"from": "service", "days": -1, "working": True, "holidays": "PL"}
    )
    assert rule.count(date(2026, 9, 21)) == date(2026, 9, 18)
    assert DayShift.model_validate({"from": "service", "days": -1}).count(date(2026, 9, 21)) == (
        date(2026, 9, 20)
    )
    with pytest.raises(ValueError, match="not known"):
        DayShift.model_validate({"from": "s", "days": -1, "working": True, "holidays": "XX"})
    with pytest.raises(ValueError, match="only valid with"):
        DayShift.model_validate({"from": "s", "days": -1, "holidays": "PL"})
