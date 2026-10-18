"""Where a value came from: the column of the table the person worked from.

A recording made with ``--data`` keeps a copy of the sheet the person took values from.
Each value typed on screen is compared with the cells of that sheet: as text, as an amount
(135 = 135.00 = 135,00) and as a date in the usual ways of writing one (2027-01-15 =
15.01.2027 = 01/15/2027 00:00:00). The row is the one that holds the most of the
recording's values, or the one row holding a document's number no other cell of the sheet
holds, when that number is all the sheet gave (the quantities were counted on the spot). A
column counts only when every recording that has a sheet agrees on it, so a value that only
happened to be in two columns once is not bound by chance.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from maptelo.data.tables import Table
from maptelo.mapping.shown import TRADE_MARKS, distinctive
from maptelo.model.schema import COUNTRY_CODE, LIKE_MASK, NATIONAL, ZERO_MASK, national

DATES = ["%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d.%m.%y"]
TIMES = ["", " %H:%M:%S", " %H:%M"]
_AMOUNT = re.compile(r"-?\d+(?:[.,]\d+)?")
ZEROS_FIRST = re.compile(r"0\d+")
"""Digits only, starting with a zero: a number written to a width (000000302)."""
_DOCUMENT = re.compile(r"(?=.*\d)(?=.*[^\W\d_])\S.{3,}\S")
"""A document's number or code ("ZW/2026/002", "FV/193/10/2026", "PO-2026-0001"): letters
and digits, at least five signs. An amount, a quantity or a plain word may be in any row."""

Kind = Literal["text", "number", "date", "time"]
_PHONE = re.compile(r"\+?[\d\s().-]{7,}")
"""How a phone number is written: digits, spaces, dashes, brackets, a plus first."""
TIME_FORMS = ["%I:%M%p", "%I:%M %p", "%H:%M", "%H:%M:%S", "%I:%M:%S %p"]
"""How a time of day is written: 9:22AM, 9:22 AM, 09:22, 09:22:00."""


@dataclass(frozen=True)
class Origin:
    """A column a value can come from, and how it is typed on screen."""

    column: str
    kind: Kind = "text"
    typed_as: str | None = None
    """A date pattern, an amount format (0.00 / 0,00) or a number's width in zeros
    (000000000), when typing changes the cell."""
    written_as: str | None = None
    """How the sheet writes a date as text (%m/%d/%Y), when not as YYYY-MM-DD."""


@dataclass
class Provenance:
    origins: dict[str, Origin] = field(default_factory=dict)
    """Input -> its column, where every recording with a sheet agrees on exactly one."""
    doubtful: dict[str, list[Origin]] = field(default_factory=dict)
    """Input -> the columns still possible (several fit, or the recordings disagree)."""
    rows: list[dict[str, str] | None] = field(default_factory=list)
    """Per recording: the row its values came from (None: no sheet, or no row fits)."""

    @property
    def support(self) -> int:
        """Recordings whose values were found in a row of their sheet."""
        return sum(row is not None for row in self.rows)


def _amount(text: str) -> Decimal | None:
    cleaned = text.strip().replace(chr(0xA0), "").replace(" ", "")
    if _AMOUNT.fullmatch(cleaned) is None:
        return None
    return Decimal(cleaned.replace(",", "."))


def _moment(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.strip())
    except ValueError:
        return None


def readings(cell: str, typed: str) -> set[tuple[Kind, str | None]]:
    """How the typed text can be this cell's value: (kind, typed_as); empty if it cannot."""
    found: set[tuple[Kind, str | None]] = set()
    cell, typed = cell.strip(), typed.strip()
    if not cell or not typed:
        return found
    moment = _moment(cell) if re.match(r"\d{4}-\d{2}-\d{2}", cell) else None
    if moment is not None:
        if typed == cell:
            found.add(("date", None))
        from maptelo.dates import oracle_masks, read_oracle_date

        if read_oracle_date(typed) == moment.date():
            found.update(("date", mask) for mask in oracle_masks(typed))
        for day in DATES:
            for clock in TIMES:
                pattern = day + clock
                if pattern != "%Y-%m-%d" and moment.strftime(pattern) == typed:
                    found.add(("date", pattern))
        return found
    # „Gobi HeatTec Tee” typed for the sheet's „Gobi HeatTec® Tee”; a file by its name for its path
    if typed == cell or _words(typed) == _words(cell) or _file_of(cell, typed):
        found.add(("text", None))
    if _phone(cell) and typed == national(cell):  # +1 2058812302 typed as 2058812302
        found.add(("text", NATIONAL))  # (a number written without a code: as it is, too)
    if is_search(cell, typed):
        found.add(("text", LIKE))
    words = _around(cell, typed)
    if words is not None:
        found.add(("text", words))
    amount, written = _amount(cell), _amount(typed)
    if amount is not None and written is not None and amount == written and typed != cell:
        if ZEROS_FIRST.fullmatch(typed) and cell.isdigit():
            # a number written to a width with its leading zeros: the order 000000302 the
            # application's search knows, for the sheet's 302 (Excel drops the zeros)
            found.add(("number", "0" * len(typed)))
            return found
        separator = "," if "," in typed else "."
        places = len(typed.partition(separator)[2]) if separator in typed else 0
        found.add(("number", "0" + (separator + "0" * places if places else "")))
    return found


def _file_of(cell: str, typed: str) -> bool:
    """The file a person chose, told by its name alone (a browser's upload: cennik_K0009.xlsx),
    is the file the cell names by its path (C:\\Zespol\\Cenniki\\cennik_K0009.xlsx)."""
    if not re.search(r"[\\/]", cell) or re.search(r"[\\/]", typed) or "." not in typed:
        return False
    return re.split(r"[\\/]", cell.rstrip("\\/"))[-1].casefold() == typed.casefold()


def _phone(text: str) -> bool:
    """A phone number: seven digits or more, written the ways phone numbers are."""
    plain = text.strip()
    digits = sum(ch.isdigit() for ch in plain)
    return (
        digits >= 7
        and _PHONE.fullmatch(plain) is not None
        and (COUNTRY_CODE.match(plain) is not None or not plain.startswith("+"))
    )


def _words(text: str) -> str:
    """Text as compared with a cell: any case and spacing, without ®/™ marks."""
    return " ".join(TRADE_MARKS.sub("", text).split()).casefold()


def _searched_by(cell: str, typed: str) -> bool:
    """The typed words are the first words of the cell („Gobi” for „Gobi HeatTec Tee”): what a
    person types into a search box to find the record (WebArena-Verified)."""
    words, said = _words(cell), _words(typed)
    return len(said) >= 3 and (words == said or words.startswith(said + " "))


def written_dates(cell: str, typed: str) -> set[tuple[str, str | None]]:
    """How a date the sheet writes as text („09/10/2012”, „15.01.2027”) can be the typed one:
    (the sheet's pattern, the typed pattern; None when typed as YYYY-MM-DD, as a date field
    holds it). A cell both ways of the day and the month read gives both: another recording
    tells them apart (02/24/2017 is no 24th month)."""
    cell, typed = cell.strip(), typed.strip()
    if not cell or not typed or re.match(r"\d{4}-\d{2}-\d{2}", cell):
        return set()
    found: set[tuple[str, str | None]] = set()
    for day in DATES:
        for clock in TIMES:
            written = day + clock
            try:
                moment = datetime.strptime(cell, written)
            except ValueError:
                continue
            for typed_day in DATES:
                for typed_clock in TIMES:
                    pattern = typed_day + typed_clock
                    if moment.strftime(pattern) == typed:
                        found.add((written, None if pattern == "%Y-%m-%d" else pattern))
    return found


def written_times(cell: str, typed: str) -> set[tuple[str, str | None]]:
    """How a time the sheet writes („9:22AM”) can be the typed one („09:22”, a time field's
    value): (the sheet's pattern, the typed pattern; None when typed as HH:MM)."""
    cell, typed = cell.strip(), typed.strip()
    if not cell or not typed or not any(ch.isdigit() for ch in cell):
        return set()
    found: set[tuple[str, str | None]] = set()
    for written in TIME_FORMS:
        try:
            moment = datetime.strptime(cell.upper(), written)
        except ValueError:
            continue
        for pattern in TIME_FORMS:
            if moment.strftime(pattern).casefold() == typed.casefold():
                found.add((written, None if pattern == "%H:%M" else pattern))
    return {(w, t) for w, t in found if not (w == "%H:%M" and t is None)}  # same text: text


def _fits(row: Mapping[str, str], typed: str, *, search: bool = False) -> set[Origin]:
    """``search``: the value went into a search box, where the first words of the record's
    value find it as well as all of them (the full value is typed then)."""
    searched = {Origin(c) for c, cell in row.items() if search and _searched_by(cell, typed)}
    found = {
        Origin(column, kind, typed_as)
        for column, cell in row.items()
        for kind, typed_as in readings(cell, typed)
    }
    around = {o for o in found if o.typed_as is not None and "{}" in o.typed_as}
    whole = {o for o in found if o.kind == "text" and o.typed_as is None}
    if whole and around:  # the value itself in one cell, words around another's (M7's file)
        found = whole
    elif len(around) > 1 and around == found:
        # the words around one value hold another (a file's path: cennik_K0010_2026-11.csv
        # holds the customer's K0010, benchmark M3): the value is the one that covers the most
        # of what was typed
        longest = max(len(row[o.column].strip()) for o in around)
        found = {o for o in around if len(row[o.column].strip()) == longest}
    return (
        searched
        | found
        | {
            Origin(column, "date", typed_as, written_as)
            for column, cell in row.items()
            for written_as, typed_as in written_dates(cell, typed)
        }
        | {
            Origin(column, "time", typed_as, written_as)
            for column, cell in row.items()
            for written_as, typed_as in written_times(cell, typed)
        }
    )


LIKE = "{}%"
"""The value typed as a search's beginning (model.schema.LIKE_MASK)."""


def is_search(cell: str, typed: str) -> bool:
    """The typed text is a search for the cell: its beginning (at least three signs), then %
    (K0010% for K0010, 26386% for 26386-F: Oracle Forms' list of values finds it so)."""
    head = typed.strip()
    if not head.endswith("%") or "%" in head[:-1] or "_" in head:
        return False
    head = head[:-1]
    return len(head) >= 3 and cell.strip().casefold().startswith(head.casefold())


_DISTINCT = re.compile(r"(?=.*\d)(?=.*[^\W\d_]).{5,}|\S{10,}")
"""A cell's value that may be found inside other words by itself: letters and digits, five signs
at least (WZ/2026/01018, K0010), or a long word; a number or a short word is in any text."""


def _around(cell: str, typed: str) -> str | None:
    """The words typed around the cell's value, with {} where it is ("Kwota netto niezgodna z
    dokumentem {}." for WZ/2026/01018): a description written for this record (benchmark M6).
    None when the value is not there once, or could be there by chance."""
    value = cell.strip()
    if typed == value or not _DISTINCT.fullmatch(value) or typed.count(value) != 1:
        return None
    return typed.replace(value, "{}")


def _meet(first: set[Origin], second: set[Origin]) -> set[Origin]:
    """The origins two recordings agree on. A value typed whole in one and as a search's
    beginning in the other (26386-F, then 31830% and a row of the list) is the column's value:
    typed whole, it finds the same row."""
    both = first & second
    for column in {o.column for o in first | second if o.kind == "text"}:
        plain, search = Origin(column, "text", None), Origin(column, "text", LIKE)
        if (
            ({plain, search} & first)
            and ({plain, search} & second)
            and not ({plain, search} & both)
        ):
            both.add(plain)
    return both


def _row(table: Table, values: Mapping[str, str]) -> dict[str, str] | None:
    """The row holding the most of the values, of those the one whose cells cover the most of
    what was typed; None when no row stands out. One value is enough when it is a document's
    number that one cell of the whole sheet holds (the rest was typed from elsewhere: counted,
    read on another screen)."""
    scores = [_score(row, values) for row in table.rows]
    if not scores:
        return None
    best = max(scores)
    if best[0] >= min(2, len(values)) and scores.count(best) == 1:
        return table.rows[scores.index(best)]
    only = table.rows[0] if len(table.rows) == 1 else None
    if only is not None and any(distinctive(t) and _fits(only, t) for t in values.values()):
        return only  # the sheet of one record (a task's values), named by a value of its own
    numbers = [typed for typed in values.values() if _DOCUMENT.fullmatch(typed.strip())]
    hits = [i for typed in numbers for i, row in enumerate(table.rows) if _fits(row, typed)]
    if best[0] == 1 and len(hits) == 1:
        return table.rows[hits[0]]
    return None  # too little of it is there, or two rows fit as well


def _score(row: Mapping[str, str], values: Mapping[str, str]) -> tuple[int, int]:
    """How many of the values the row holds, and how much of what was typed its cells cover
    (a file's path holds the customer's K0010, which two rows of the sheet have, and the
    file's name, which one row has: benchmark M3)."""
    held = covered = 0
    for typed in values.values():
        fits = _fits(row, typed)
        if fits:
            held += 1
            covered += max(len(row[o.column].strip()) for o in fits)
    return held, covered


def trace_origins(
    examples: Sequence[Mapping[str, str]],
    tables: Sequence[Table | None],
    searches: Collection[str] = (),
) -> Provenance:
    """Which column each input came from, from recordings with their sheets.

    ``examples[i]`` holds the values typed in recording i (input -> text) and
    ``tables[i]`` the sheet it was made with (None when it had none); ``searches``: the inputs
    typed into a search box."""
    result = Provenance()
    possible: dict[str, set[Origin]] = {}
    for values, table in zip(examples, tables, strict=True):
        row = _row(table, values) if table is not None and values else None
        result.rows.append(row)
        if row is None:
            continue
        for name, typed in values.items():
            fits = _fits(row, typed, search=name in searches)
            possible[name] = fits if name not in possible else _meet(possible[name], fits)
    for name, origins in possible.items():
        if len(origins) == 1:
            result.origins[name] = next(iter(origins))
        else:
            columns = {o.column for o in origins}
            if len(columns) == 1 and len({o.written_as for o in origins}) > 1:
                result.doubtful[name] = sorted(origins, key=lambda o: str(o.written_as))
            elif len(columns) == 1:  # one column, read in several ways: prefer the plainest
                result.origins[name] = min(origins, key=lambda o: (o.typed_as is not None, o.kind))
            elif origins:
                result.doubtful[name] = sorted(origins, key=lambda o: o.column)
    return result


def bind(spec: dict[str, Any], origin: Origin, row: Mapping[str, str]) -> None:
    """An input taken from a column of the sheet: the column, and how its value is typed on
    screen (a date's mask, a number's zeros, K0010% searched for, words around the value)."""
    spec["column"] = origin.column
    cell = (row.get(origin.column) or "").strip()
    if origin.kind == "date":
        spec["type"] = "date"
        spec["example"] = (cell or str(spec.get("example") or ""))[:10]
        spec.pop("pattern", None)
        if origin.written_as is not None and cell:  # the sheet's „09/10/2012”: read so
            spec["written_as"] = origin.written_as
            spec["example"] = datetime.strptime(cell, origin.written_as).date().isoformat()
    if origin.kind == "time":  # the sheet's „9:22AM” typed as 09:22
        spec["type"] = "time"
        spec.pop("pattern", None)
        if origin.written_as is not None and cell:
            spec["written_as"] = origin.written_as
            clock = datetime.strptime(cell.upper(), origin.written_as)
            spec["example"] = clock.strftime("%H:%M")
    if origin.typed_as is None:
        return
    if ZERO_MASK.fullmatch(origin.typed_as):
        if spec["type"] in ("string", "integer"):  # the order 000000302 for 302
            spec["typed_as"] = origin.typed_as
    elif origin.typed_as == NATIONAL and spec["type"] == "string":
        spec["typed_as"] = NATIONAL  # the phone +1 2058812302 typed as 2058812302
    elif origin.typed_as == LIKE_MASK or "{}" in origin.typed_as:
        # K0010% searched for, or words written around the value: the value as text
        spec["type"] = "string"
        spec.pop("pattern", None)
        spec["typed_as"] = origin.typed_as
    elif spec["type"] in ("date", "decimal", "time"):
        spec["typed_as"] = origin.typed_as
