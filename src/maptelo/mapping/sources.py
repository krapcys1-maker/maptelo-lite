"""Where a value came from: the column of the table the person worked from.

A recording made with ``--data`` keeps a copy of the sheet the person took values from.
Each value typed on screen is compared with the cells of that sheet: as text in any case,
as an amount (135 = 135.00 = 135,00) and as a date in the usual ways of writing one
(2027-01-15 = 15.01.2027 = 01/15/2027 00:00:00 = 15/January/2027 = 15-JAN-2027, and Excel's
number of the day in a CSV file), with words around it („Account 604217359” for the account)
or as the part of it after a separator (5510 of „CENNIK_ZK_5510”). The row is the one
that holds the most of the recording's values, or the one row holding a document's number no
other cell of the sheet holds, when that number is all the sheet gave (the quantities were
counted on the spot). A column counts only when every recording that has a sheet agrees on it,
so a value that only happened to be in two columns once is not bound by chance.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal

from maptelo.data.tables import Table
from maptelo.mapping.shown import TRADE_MARKS, distinctive
from maptelo.model.schema import COUNTRY_CODE, LIKE_MASK, NATIONAL, ZERO_MASK, national

DATES = [
    "%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d.%m.%y",
    "%d/%B/%Y", "%d %B %Y", "%d.%B.%Y", "%d/%b/%Y", "%d %b %Y",
]  # fmt: skip
"""How dates are written: with numbers, and with the month's English name (15/November/2026,
15 Nov 2026); Oracle's 15-NOV-2026 has a mask of its own (maptelo.dates)."""
TIMES = ["", " %H:%M:%S", " %H:%M"]
_AMOUNT = re.compile(r"-?\d+(?:[.,]\d+)?")
ZEROS_FIRST = re.compile(r"0\d+")
"""Digits only, starting with a zero: a number written to a width (000000302)."""
_DOCUMENT = re.compile(r"(?=.*\d)(?=.*[^\W\d_])\S.{3,}\S")
"""A document's number or code ("ZW/2026/002", "FV/193/10/2026", "PO-2026-0001"): letters
and digits, at least five signs. An amount, a quantity or a plain word may be in any row."""

Kind = Literal["text", "number", "date", "time", "part"]
"""How a cell is typed: as its text, as an amount, a date, a time, or a part of it (``part``:
what follows a separator, the separator in ``typed_as``)."""
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
    (000000000), when typing changes the cell; of a ``part``, the separator it follows."""
    written_as: str | None = None
    """How the sheet writes a date as text (%m/%d/%Y, DD-MON-YYYY, Excel's number of the
    day), when not as YYYY-MM-DD."""
    per: str | None = None
    """The column whose number the cell is divided by (a price for 1000 pieces typed for one)."""


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


def typed_forms(moment: datetime, typed: str) -> set[str]:
    """The patterns ``typed`` writes the moment in: Oracle's mask (01-NOV-2026, 01-LIS-2026),
    a pattern of numbers or of the month's name (01.11.2026, 01/November/2026), in any case;
    %Y-%m-%d for the date written as a date field holds it."""
    from maptelo.dates import oracle_masks, read_oracle_date

    found: set[str] = set()
    if read_oracle_date(typed) == moment.date():
        found.update(oracle_masks(typed))
    for day in DATES:
        for clock in TIMES:
            pattern = day + clock
            if moment.strftime(pattern).casefold() == typed.casefold():
                found.add(pattern)
    return found


@lru_cache(maxsize=4096)
def cell_days(cell: str) -> frozenset[tuple[datetime, str]]:
    """The moments a cell not written as YYYY-MM-DD can be, with how it writes them (a
    pattern, Oracle's mask, Excel's number of the day). A cell both ways of the day and the
    month read gives both (09/10/2012)."""
    from maptelo.dates import EXCEL_SERIAL, excel_day, oracle_masks, read_oracle_date

    if not any(ch.isdigit() for ch in cell):
        return frozenset()
    found: set[tuple[datetime, str]] = set()
    for day in DATES:
        for clock in TIMES:
            written = day + clock
            try:
                found.add((datetime.strptime(cell, written), written))
            except ValueError:
                continue
    oracle = read_oracle_date(cell)
    if oracle is not None:
        moment = datetime(oracle.year, oracle.month, oracle.day)
        found.update((moment, mask) for mask in oracle_masks(cell))
    serial = excel_day(cell)
    if serial is not None:
        found.add((datetime(serial.year, serial.month, serial.day), EXCEL_SERIAL))
    return frozenset(found)


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
        found.update(("date", p) for p in typed_forms(moment, typed) if p != "%Y-%m-%d")
        return found
    # „Gobi HeatTec Tee” typed for the sheet's „Gobi HeatTec® Tee”; a file by its name for its path
    if typed == cell or _words(typed) == _words(cell) or _file_of(cell, typed):
        found.add(("text", None))
    # +1 2058812302 typed as 2058812302 (a number written without a code: as it is, too); a
    # date of the sheet („15.01.2027”) is no phone number
    if _phone(cell) and typed == national(cell) and not cell_days(cell):
        found.add(("text", NATIONAL))
    if is_search(cell, typed):
        found.add(("text", LIKE))
    words = _around(cell, typed)
    if words is not None:
        found.add(("text", words))
    after = _part_after(cell, typed)
    if after is not None:
        found.add(("part", after))
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
    elif amount is not None and typed == cell and re.fullmatch(r"-?\d+[.,]\d+", typed):
        # an amount typed as the cell writes it is also that number in that form: another
        # recording typed 2.00 for the cell's 2, and both are the column's price
        separator = "," if "," in typed else "."
        found.add(("number", "0" + separator + "0" * len(typed.partition(separator)[2])))
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


_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def written_dates(cell: str, typed: str) -> set[tuple[str, str | None]]:
    """How a date the sheet writes as text („09/10/2012”, „15.01.2027”) can be the typed one:
    (the sheet's pattern, the typed pattern; None when typed as YYYY-MM-DD, as a date field
    holds it). A cell both ways of the day and the month read gives both: another recording
    tells them apart (02/24/2017 is no 24th month)."""
    cell, typed = cell.strip(), typed.strip()
    # every way of writing a date here starts with a digit: most cells are no date at all
    if not cell[:1].isdigit() or not typed[:1].isdigit() or _ISO_DAY.match(cell):
        return set()
    return {
        (written, None if pattern == "%Y-%m-%d" else pattern)
        for moment, written in cell_days(cell)
        for pattern in typed_forms(moment, typed)
    }


def written_times(cell: str, typed: str) -> set[tuple[str, str | None]]:
    """How a time the sheet writes („9:22AM”) can be the typed one („09:22”, a time field's
    value): (the sheet's pattern, the typed pattern; None when typed as HH:MM)."""
    cell, typed = cell.strip(), typed.strip()
    if not cell[:1].isdigit() or not typed[:1].isdigit():  # every time here starts so
        return set()
    said = typed.casefold()
    found = {
        (written, None if pattern == "%H:%M" else pattern)
        for written, moment in _times_in(cell.upper())
        for pattern in TIME_FORMS
        if moment.strftime(pattern).casefold() == said
    }
    return {(w, t) for w, t in found if not (w == "%H:%M" and t is None)}  # same text: text


@lru_cache(maxsize=1 << 16)
def _times_in(cell: str) -> tuple[tuple[str, datetime], ...]:
    found = []
    for written in TIME_FORMS:
        try:
            found.append((written, datetime.strptime(cell, written)))
        except ValueError:
            continue
    return tuple(found)


_COUNT = re.compile(r"\s*(\d{1,7})(?:\s+\S.*)?")
"""A count, with the unit it counts (1000 szt., 100 kg, 1): what a price may be for."""


def per_count(cell: str) -> int | None:
    found = _COUNT.fullmatch(cell or "")
    return int(found.group(1)) if found and int(found.group(1)) > 0 else None


def _divided(row: Mapping[str, str], typed: str) -> set[Origin]:
    """The cells that, divided by the count of another cell of the row, are the typed number
    (6040,00 for 1000 szt. typed as 6,04): the person typed the price of one unit."""
    written = _amount(typed)
    if written is None:
        return set()
    exponent = written.as_tuple().exponent
    places = -exponent if isinstance(exponent, int) else 0
    found = set()
    for column, cell in row.items():
        amount = _amount(cell)
        if amount is None:
            continue
        for per_column, per_cell in row.items():
            count = per_count(per_cell) if per_column != column else None
            if count is None:
                continue
            value = amount / count
            if value == written or value.quantize(Decimal(1).scaleb(-max(places, 0))) == written:
                separator = "," if "," in typed else "."
                fraction = separator + "0" * max(places, 0) if places > 0 else ""
                found.add(Origin(column, "number", "0" + fraction, per=per_column))
    return found


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
    parts = {o for o in found if o.kind == "part"}
    if whole and parts:  # the value itself in one cell, the end of another's: the cell's
        found -= parts
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
        | _divided(row, typed)
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


_LONG_NUMBER = re.compile(r"\d{6,}")
"""An account's or a customer's number: six digits or more, which stand in a text by chance only
as a part of a longer number."""


def _around(cell: str, typed: str) -> str | None:
    """The words typed around the cell's value, with {} where it is ("Kwota netto niezgodna z
    dokumentem {}." for WZ/2026/01018, „Account {}” for the account 604217359): a description
    written for this record (benchmark M6). The value in any case; a long number only as a
    word of its own. None when the value is not there once, or could be there by chance."""
    value = cell.strip()
    number = _LONG_NUMBER.fullmatch(value) is not None
    if typed.casefold() == value.casefold() or not (_DISTINCT.fullmatch(value) or number):
        return None
    edge = r"(?<![\w.,])" if number else ""
    found = list(re.finditer(edge + re.escape(value) + edge.replace("<", ""), typed, re.I))
    if len(found) != 1:
        return None
    return typed[: found[0].start()] + "{}" + typed[found[0].end() :]


_SEPARATOR = re.compile(r"[\W_]+(?:[^\W\d_]{1,4}[\W_]+)?$")
"""What ends the part of a value before the part typed: signs („-”, „ / ”), or a short word
between them („_ZK_”)."""


def _part_after(cell: str, typed: str) -> str | None:
    """The separator the typed text follows at the end of the cell (the order's 5510 of
    the price list's name „CENNIK_ZK_5510”: „_ZK_”): the part of the value a field wants.
    None when the typed text is no such end, or is too short not to be there by chance."""
    value, part = cell.strip(), typed.strip()
    if len(part) < 3 or len(part) >= len(value) or not value.casefold().endswith(part.casefold()):
        return None
    before = value[: len(value) - len(part)]
    separator = _SEPARATOR.search(before)
    if separator is None or separator.start() == 0 or not re.search(r"\w", part[0]):
        return None
    if not separator.group().strip():
        return None  # a space only: the last word of a description („… K0010 2026”)
    if not (distinctive(part) or any(ch.isdigit() for ch in part)):
        return None  # a short word at the end of a name („_ZK_ABC”) is in many names
    return separator.group()


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


_ROWS: dict[tuple[int, tuple[tuple[str, str], ...], bool], tuple[Table, dict[str, str] | None]] = {}
"""Rows found, by the sheet and the values: a build asks again for the same recording's row
(each of its questions about where values come from); the sheet is kept with its row, so its
id is not another sheet's."""


def _row(
    table: Table, values: Mapping[str, str], *, together: bool = False
) -> dict[str, str] | None:
    key = (id(table), tuple(sorted(values.items())), together)
    known = _ROWS.get(key)
    if known is not None and known[0] is table:
        return known[1]
    row = _row_of(table, values, together=together)
    if len(_ROWS) >= 256:
        _ROWS.pop(next(iter(_ROWS)))
    _ROWS[key] = (table, row)
    return row


def _row_of(
    table: Table, values: Mapping[str, str], *, together: bool = False
) -> dict[str, str] | None:
    """The row holding the most of the values, of those the one whose cells cover the most of
    what was typed; None when no row stands out. One value is enough when it is a document's
    number that one cell of the whole sheet holds (the rest was typed from elsewhere: counted,
    read on another screen). ``together``: rows of one record (its lines) stand out together,
    a value naming them and each holding every value the same way, so any of them gives the
    columns (a price list's header typed once, its lines chosen from a list)."""
    scores = [_score(row, values) for row in table.rows]
    if not scores:
        return None
    numbers = [typed for typed in values.values() if _DOCUMENT.fullmatch(typed.strip())]
    hits = [i for typed in numbers for i, row in enumerate(table.rows) if _fits(row, typed)]
    if len(set(hits)) == 1 and len(hits) == len(numbers):
        # the document's number names the record: dates another row holds by chance (its
        # issue date the same day as this one's rate day) do not outweigh it
        return table.rows[hits[0]]
    best = max(scores)
    if best[0] >= min(2, len(values)) and scores.count(best) == 1:
        return table.rows[scores.index(best)]
    tied = [row for row, score in zip(table.rows, scores, strict=True) if score == best]
    named = any(distinctive(t) and _fits(tied[0], t) for t in values.values())
    if (
        together
        and best[0] >= min(2, len(values))
        and named
        and all(_fits(r, typed) == _fits(tied[0], typed) for r in tied for typed in values.values())
    ):
        # the rows of one record (its lines, a price list's): a value naming it and the rest of
        # its header the same in each, so the same columns whichever of them is taken
        return tied[0]
    only = table.rows[0] if len(table.rows) == 1 else None
    if only is not None and any(distinctive(t) and _fits(only, t) for t in values.values()):
        return only  # the sheet of one record (a task's values), named by a value of its own
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
    *,
    together: bool = False,
    lines: Collection[str] = (),
) -> Provenance:
    """Which column each input came from, from recordings with their sheets.

    ``examples[i]`` holds the values typed in recording i (input -> text) and
    ``tables[i]`` the sheet it was made with (None when it had none); ``searches``: the inputs
    typed into a search box; ``together``: the rows of one record may stand out together (a
    map of one recording, whose header its rows share: ``_row``); ``lines``: the inputs with
    a value for each line of the record, whose example may be another line's (a warehouse
    typed for some lines only), found in the record's other rows."""
    result = Provenance()
    possible: dict[str, set[Origin]] = {}
    for values, table in zip(examples, tables, strict=True):
        row = _row(table, values, together=together) if table is not None and values else None
        result.rows.append(row)
        if row is None or table is None:
            continue
        header = {o.column for n, t in values.items() if n not in lines for o in _fits(row, t)}
        # the record's rows: most of the header's cells the same (a value the form wrote
        # beside a line's field, its item's name, is no header's however it was taken)
        record = [
            r for r in table.rows if 2 * sum(r.get(c) == row.get(c) for c in header) > len(header)
        ]
        for name, typed in values.items():
            fits = _fits(row, typed, search=name in searches)
            if not fits and name in lines and header:
                fits = set().union(*(_fits(r, typed) for r in record))
            possible[name] = fits if name not in possible else _meet(possible[name], fits)
    for name, origins in possible.items():
        if len({o.column for o in origins}) == 1 and any(o.kind == "date" for o in origins):
            # the sheet's „15.01.2027” typed as it stands is the date, not a text of it
            origins = {o for o in origins if o.kind == "date"}
        if len(origins) == 1:
            result.origins[name] = next(iter(origins))
        else:
            columns = {o.column for o in origins}
            if len(columns) == 1 and len({o.written_as for o in origins}) > 1:
                result.doubtful[name] = sorted(origins, key=lambda o: str(o.written_as))
            elif len(columns) == 1:  # one column, read in several ways: the plainest (no division)
                result.origins[name] = min(
                    origins, key=lambda o: (o.per is not None, o.typed_as is not None, o.kind)
                )
            elif origins:
                result.doubtful[name] = sorted(origins, key=lambda o: o.column)
    return result


def bind(spec: dict[str, Any], origin: Origin, row: Mapping[str, str]) -> None:
    """An input taken from a column of the sheet: the column, and how its value is typed on
    screen (a date's mask, a number's zeros, K0010% searched for, words around the value)."""
    spec["column"] = origin.column
    cell = (row.get(origin.column) or "").strip()
    if origin.per is not None:  # a price for 1000 pieces: the value typed is for one
        spec["per_column"] = origin.per
        spec["type"] = "decimal"
        spec.pop("pattern", None)
    if origin.kind == "part" and origin.typed_as is not None:  # 5510 of „CENNIK_ZK_5510”
        spec["type"] = "string"
        spec.pop("pattern", None)
        spec["taken_after"] = origin.typed_as
        return
    if origin.kind == "date":
        from maptelo.dates import written_day

        spec["type"] = "date"
        spec["example"] = (cell or str(spec.get("example") or ""))[:10]
        spec.pop("pattern", None)
        day = written_day(cell, origin.written_as) if origin.written_as and cell else None
        if origin.written_as is not None and day is not None:  # the sheet's „09/10/2012”
            spec["written_as"] = origin.written_as
            spec["example"] = day.isoformat()
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
