"""Picking a day in a calendar as a person does: see which days (and which month) the
calendar shows, move it month by month towards the date, click the day. The runtime and the
exported script run this same code, for a 'pick_date' step and its ``Calendar``.

Days are read from their names: whole dates ("24 listopada 2026"), dates without the year
("24 listopada") or only numbers ("24"), where the month shown over them says the rest; the
numbers before the month's 1 end the month before, those after its last day begin the next.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date
from typing import Any

from playwright.sync_api import Error as PlaywrightError

from maptelo.dates import day_name, find_day, read_day, read_month, same_way

Find = Callable[[list[dict[str, Any]]], Any]
"""Finds the one element a locator ladder (a list of rungs) names, or None."""


# The exported script carries this module from here on (export/playwright_py.py).

MOST_MONTHS = 120
"""How many times a calendar is moved towards a day before giving up (ten years)."""

CELLS_JS = """els => els.map(e => [
  (e.getAttribute('aria-label') || e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim(),
  Boolean(e.disabled || e.closest('[aria-disabled=true]')
    || /(^|[\\s_-])disabled($|[\\s_-])/i.test(e.getAttribute('class') || '')),
])"""
"""The name of each day and whether it cannot be picked (disabled, by attribute or class)."""

TEXTS_JS = """box => {
  const seen = [];
  for (const e of [box, ...box.querySelectorAll('*')]) {
    if (!e.getClientRects().length) continue;
    for (const text of [e.innerText, e.getAttribute('aria-label'), e.getAttribute('title')]) {
      const said = (text || '').replace(/\\s+/g, ' ').trim();
      if (said && said.length <= 40 && !seen.includes(said)) seen.push(said);
    }
  }
  return seen.slice(0, 400);
}"""
"""The short texts shown in the calendar: among them the month over its days."""


class CalendarError(Exception):
    """The day cannot be picked in the calendar; the message says why."""


def _on(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def numbered_days(names: list[str], year: int, month: int) -> list[date | None]:
    """The dates of days named only by their number, in the order shown, in a calendar
    showing ``month``: it runs from its 1; numbers before that end the month before, numbers
    after its last day begin the next."""
    numbers = [int(n) if n.isdigit() and 1 <= int(n) <= 31 else None for n in names]
    dates: list[date | None] = [None] * len(names)
    first = next((i for i, n in enumerate(numbers) if n == 1), None)
    if first is None:
        return dates
    before = (year, month - 1) if month > 1 else (year - 1, 12)
    after = (year, month + 1) if month < 12 else (year + 1, 1)
    for i, number in enumerate(numbers[:first]):
        if number is not None and number > 20:
            dates[i] = _on(*before, number)
    shown, last = (year, month), 0
    for i in range(first, len(numbers)):
        number = numbers[i]
        if number is None:
            continue
        if number < last and shown == (year, month):
            shown = after
        last = number
        dates[i] = _on(*shown, number)
    return dates


def days_of(names: list[str], pattern: str, shown: tuple[int, int] | None) -> list[date | None]:
    """The date of each day from its name; what the name leaves out (the year, or the month
    and year) from the month ``shown`` over the days."""
    if "{yyyy}" in pattern:
        dates: list[date | None] = []
        for name in names:
            read = read_day(name)
            dates.append(read[0] if read and same_way(read[1], pattern) else None)
        return dates
    if shown is None:
        return [None] * len(names)
    year, month = shown
    if not any(field in pattern.lower() for field in ("{month", "{m}", "{mm}")):
        return numbered_days(names, year, month)
    dates = []
    for name in names:  # "24 listopada": the year of the month shown, or of the one next to it
        found = find_day(name)
        if found is None or not same_way(found[3], pattern):
            dates.append(None)
            continue
        near = year + (1 if found[1] < month - 6 else -1 if found[1] > month + 6 else 0)
        dates.append(_on(near, found[1], found[0]))
    return dates


def month_shown(texts: list[str], pattern: str | None) -> tuple[int, int] | None:
    """The month a calendar shows, from its texts: the one month written ``pattern``'s way."""
    months = set()
    for text in texts:
        read = read_month(text)
        if read is not None and (pattern is None or same_way(read[2], pattern)):
            months.add(read[:2])
    return months.pop() if len(months) == 1 else None


def _main_months(dates: list[date | None]) -> list[tuple[int, int]]:
    """The months a calendar shows whole (not the few days of the months next to them)."""
    counts: dict[tuple[int, int], int] = {}
    for day in dates:
        if day is not None:
            counts[day.year, day.month] = counts.get((day.year, day.month), 0) + 1
    whole = sorted(month for month, count in counts.items() if count >= 20)
    return whole or sorted(counts)


def _look(page: Any, calendar: dict[str, Any], find: Find) -> Any:
    """What the calendar shows now: (its days, their names, which cannot be picked, their
    dates, the month shown); None when it shows no days. A calendar known by where it is
    and not shown yet (it opens a moment after its field) is waited for: the page around
    it is never read instead, its buttons "1", "2" are no days."""
    scope = find(calendar["box"]) if calendar.get("box") else page
    if scope is None:
        return None
    rung = calendar.get("days") or {"role": "gridcell"}
    cells = scope.get_by_role(rung["role"]) if "role" in rung else scope.locator(rung["css"])
    cells = cells.filter(visible=True)
    try:
        read = cells.evaluate_all(CELLS_JS)
        shown = None
        if "{yyyy}" not in calendar["day"]:
            holder = scope if scope is not page else page.locator("body")
            shown = month_shown(holder.evaluate(TEXTS_JS), calendar.get("month"))
    except PlaywrightError:  # redrawn while being read: look again
        return None
    names = [str(name) for name, _ in read]
    dates = days_of(names, calendar["day"], shown)
    if not any(dates):
        return None
    return cells, names, [bool(off) for _, off in read], dates, shown


def pick_day(page: Any, calendar: dict[str, Any], day: date, find: Find, timeout_ms: int) -> None:
    """Click ``day`` in the open calendar, moving it month by month towards the day as a
    person does (the months it shows say which way)."""
    wanted = day_name(day, calendar["day"]) if "{yyyy}" in calendar["day"] else day.isoformat()
    deadline = time.monotonic() + timeout_ms / 1000
    moved_from: Any = None
    moves = 0
    while True:
        seen = _look(page, calendar, find)
        if seen is not None and moved_from is not None and (seen[1], seen[4]) == moved_from:
            seen = None  # not redrawn yet
        if seen is not None:  # and settled, just opened or moved: the same days twice in a row
            page.wait_for_timeout(100)
            again = _look(page, calendar, find)
            if again is None or (again[1], again[4]) != (seen[1], seen[4]):
                seen = None
        if seen is None:
            if time.monotonic() >= deadline:
                if moved_from is None:
                    raise CalendarError("the calendar shows no days")
                raise CalendarError(f"the calendar did not move towards “{wanted}”")
            page.wait_for_timeout(100)
            continue
        cells, names, off, dates, shown = seen
        moved_from = None
        here = [i for i, shown_day in enumerate(dates) if shown_day == day]
        usable = [i for i in here if not off[i]]
        if usable:
            cells.nth(usable[0]).click()
            return
        months = _main_months(dates)
        if (day.year, day.month) in months:
            if here:
                raise CalendarError(f"the day “{wanted}” cannot be picked in the calendar")
            raise CalendarError(f"the calendar shows the month, but no day “{wanted}” to click")
        forward = (day.year, day.month) > months[-1]
        way = calendar.get("next" if forward else "previous")
        button = find(way) if way else None
        if button is None:
            raise CalendarError(f"the calendar cannot be moved towards “{wanted}”")
        moves += 1
        if moves > MOST_MONTHS:
            raise CalendarError(f"the calendar did not reach “{wanted}”")
        button.click()
        moved_from = (names, shown)
        deadline = time.monotonic() + timeout_ms / 1000
