"""Working days: a date counted in days a company works, not in days of the calendar (the
NBP rate for a tax point is the one of the last working day before it, art. 31a of the VAT
act; a payment falls on the next working day). Saturdays, Sundays and the public holidays of
the country are no working days."""

from __future__ import annotations

from datetime import date, timedelta
from functools import cache

COUNTRIES = ("PL",)
"""Countries whose public holidays are known."""


def _easter(year: int) -> date:
    """Easter Sunday of the Gregorian calendar (the anonymous algorithm, Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


@cache
def holidays(country: str, year: int) -> frozenset[date]:
    """The public holidays of a year: in Poland the days free from work by the act of
    18 January 1951 (Christmas Eve free from 2025)."""
    if country != "PL":
        raise ValueError(f"public holidays of {country!r} are not known")
    easter = _easter(year)
    days = {
        date(year, 1, 1),
        date(year, 1, 6),
        easter,
        easter + timedelta(days=1),
        date(year, 5, 1),
        date(year, 5, 3),
        easter + timedelta(days=49),  # Pentecost
        easter + timedelta(days=60),  # Corpus Christi
        date(year, 8, 15),
        date(year, 11, 1),
        date(year, 11, 11),
        date(year, 12, 25),
        date(year, 12, 26),
    }
    if year >= 2025:
        days.add(date(year, 12, 24))
    return frozenset(days)


def working(day: date, country: str | None) -> bool:
    """A day people work: no Saturday, Sunday or public holiday (``country``: whose; None:
    only weekends are free)."""
    if day.weekday() >= 5:
        return False
    return country is None or day not in holidays(country, day.year)


def shift(day: date, days: int, country: str | None) -> date:
    """The date ``days`` working days after ``day`` (before it when negative): -1 is the last
    working day before it, 1 the first after it, whatever ``day`` itself is."""
    step = timedelta(days=1 if days > 0 else -1)
    left = abs(days)
    while left:
        day += step
        if working(day, country):
            left -= 1
    return day
