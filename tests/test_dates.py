"""Days and months as calendars name them: read a name into a date and its way of writing,
write any other date the same way (a robot picks a day by its name), and tell the dates of
days that are only numbers from the month shown over them."""

from __future__ import annotations

from datetime import date

import pytest

from maptelo.calendars import days_of, month_shown, numbered_days
from maptelo.dates import day_name, find_day, read_day, read_month, same_way


@pytest.mark.parametrize(
    ("name", "day", "pattern"),
    [
        ("24 listopada 2026", date(2026, 11, 24), "{d} {month} {yyyy}"),
        ("wtorek, 24 listopada 2026", date(2026, 11, 24), "{weekday}, {d} {month} {yyyy}"),
        ("Tuesday, November 24, 2026", date(2026, 11, 24), "{Weekday_en}, {Month_en} {d}, {yyyy}"),
        (
            "Tuesday, November 24th, 2026",
            date(2026, 11, 24),
            "{Weekday_en}, {Month_en} {do}, {yyyy}",
        ),
        ("November 1st, 2026", date(2026, 11, 1), "{Month_en} {do}, {yyyy}"),
        ("24 November 2026", date(2026, 11, 24), "{d} {Month_en} {yyyy}"),
        ("24.11.2026", date(2026, 11, 24), "{d}.{m}.{yyyy}"),
        ("05.03.2027", date(2027, 3, 5), "{dd}.{mm}.{yyyy}"),
        ("11/24/2026", date(2026, 11, 24), "{m}/{d}/{yyyy}"),
        ("24/11/2026", date(2026, 11, 24), "{d}/{m}/{yyyy}"),
        ("2026-11-24", date(2026, 11, 24), "{yyyy}-{mm}-{dd}"),
        (
            "Donnerstag, 24. Dezember 2026",
            date(2026, 12, 24),
            "{Weekday_de}, {d}. {Month_de} {yyyy}",
        ),
        ("mardi 24 novembre 2026", date(2026, 11, 24), "{weekday_fr} {d} {month_fr} {yyyy}"),
        ("Nov 24, 2026", date(2026, 11, 24), "{Month_en3} {d}, {yyyy}"),
        ("Sat 24 Oct 2026", date(2026, 10, 24), "{Weekday_en3} {d} {Month_en3} {yyyy}"),
    ],
)
def test_a_day_is_read_with_its_way_of_writing(name: str, day: date, pattern: str) -> None:
    assert read_day(name) == (day, pattern)
    assert day_name(day, pattern) == name  # written back the same way


def test_any_other_day_is_written_the_same_way() -> None:
    _, pattern = read_day("wtorek, 24 listopada 2026") or (None, "")
    assert day_name(date(2027, 3, 1), pattern) == "poniedziałek, 1 marca 2027"
    _, english = read_day("Tuesday, November 24th, 2026") or (None, "")
    assert day_name(date(2027, 2, 22), english) == "Monday, February 22nd, 2027"
    assert day_name(date(2027, 2, 13), english) == "Saturday, February 13th, 2027"


@pytest.mark.parametrize(
    ("name", "day"),
    [
        ("Choose Tuesday, November 24th, 2026", date(2026, 11, 24)),  # react-datepicker
        ("24 listopada 2026 r., wybrany", date(2026, 11, 24)),
        ("Dziś: 2026-11-24", date(2026, 11, 24)),
        ("11/24/2026 07:00:00", date(2026, 11, 24)),  # a field of Odoo, with its time
    ],
)
def test_a_day_is_found_among_other_words(name: str, day: date) -> None:
    found = read_day(name)
    assert found is not None
    assert found[0] == day


def test_a_day_without_its_year_says_its_day_and_month() -> None:
    assert find_day("24 listopada") == (24, 11, None, "{d} {month}")
    assert find_day("Tuesday, November 24") == (24, 11, None, "{Weekday_en}, {Month_en} {d}")
    assert read_day("24 listopada") is None  # no whole date


@pytest.mark.parametrize(
    "name",
    ["24", "Następny miesiąc", "05/03/2027", "31 lutego 2027", chr(0x203A), "May 2026", ""],
)
def test_what_is_no_day_or_cannot_be_told(name: str) -> None:
    assert read_day(name) is None


@pytest.mark.parametrize(
    ("text", "month"),
    [
        ("October 2026", (2026, 10, "{Month_en} {yyyy}")),
        ("Listopad 2026", (2026, 11, "{Month_pl} {yyyy}")),
        ("listopad 2026 r.", (2026, 11, "{month_pl} {yyyy}")),
        ("Październik, 2026", (2026, 10, "{Month_pl}, {yyyy}")),
        ("10/2026", (2026, 10, "{mm}/{yyyy}")),
        ("3.2027", (2027, 3, "{m}.{yyyy}")),
        ("2026-11", (2026, 11, "{yyyy}-{mm}")),
        ("Dezember 2026", (2026, 12, "{Month_de} {yyyy}")),
        ("décembre 2026", (2026, 12, "{month_fr} {yyyy}")),
        ("Oct 2026", (2026, 10, "{Month_en3} {yyyy}")),
    ],
)
def test_the_month_over_a_calendar_is_read(text: str, month: tuple[int, int, str]) -> None:
    assert read_month(text) == month


@pytest.mark.parametrize(
    "text",
    ["Select month", "October", "2026", "Październik 2026 - raport", "13/2026", "24.11.2026"],
)
def test_what_is_not_just_a_month(text: str) -> None:
    assert read_month(text) is None


def test_a_month_written_in_another_language_is_written_the_same_way() -> None:
    """A calendar recorded in Polish runs in English (or German): its month and its days are
    still read, the names are only another language's."""
    assert same_way("{Month_pl} {yyyy}", "{Month_en} {yyyy}")
    assert same_way("{d} {month} {yyyy}", "{d} {month_fr} {yyyy}")
    assert same_way("{Weekday_en}, {Month_en} {d}, {yyyy}", "{Weekday_de}, {Month_de} {d}, {yyyy}")
    assert not same_way("{d}. {Month_de} {yyyy}", "{d} {month} {yyyy}")  # another order of signs
    assert month_shown(["Dezember 2026"], "{Month_en} {yyyy}") == (2026, 12)


def test_ways_of_writing_differ_by_more_than_leading_zeros() -> None:
    assert same_way("{d}.{m}.{yyyy}", "{dd}.{mm}.{yyyy}")
    assert not same_way("{d}.{m}.{yyyy}", "{m}/{d}/{yyyy}")
    assert not same_way("{d} {month} {yyyy}", "{Month_en} {d}, {yyyy}")  # day and month swapped


def test_days_that_are_numbers_take_their_month_from_where_they_stand() -> None:
    # November 2026 in a grid starting on Monday: the end of October, then the beginning of December
    names = [
        "26",
        "27",
        "28",
        "29",
        "30",
        "31",
        *map(str, range(1, 31)),
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
    ]
    dates = numbered_days(names, 2026, 11)
    assert dates[0] == date(2026, 10, 26)
    assert dates[6] == date(2026, 11, 1)
    assert dates[35] == date(2026, 11, 30)
    assert dates[36] == date(2026, 12, 1)
    assert numbered_days(["31", "1", "2"], 2027, 1)[:2] == [date(2026, 12, 31), date(2027, 1, 1)]
    assert numbered_days(["", "Today", "1"], 2026, 12) == [None, None, date(2026, 12, 1)]


def test_days_without_their_year_take_it_from_the_month_shown() -> None:
    names = ["30 listopada", "1 grudnia", "31 grudnia", "1 stycznia"]
    assert days_of(names, "{d} {month}", (2026, 12)) == [
        date(2026, 11, 30), date(2026, 12, 1), date(2026, 12, 31), date(2027, 1, 1),
    ]  # fmt: skip
    assert days_of(names, "{d} {month}", None) == [None] * 4


def test_the_month_shown_is_the_one_month_among_the_texts() -> None:
    texts = ["Select month", "October 2026", "Sun", "Mon", "Previous month"]
    assert month_shown(texts, "{Month_en} {yyyy}") == (2026, 10)
    assert month_shown([*texts, "November 2026"], "{Month_en} {yyyy}") is None  # two months
    assert month_shown(["10/2026"], "{Month_en} {yyyy}") is None  # another way of writing
