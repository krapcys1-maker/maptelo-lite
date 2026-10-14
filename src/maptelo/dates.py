"""The names calendars give their days ("24 listopada 2026", "Tuesday, November 24th, 2026",
"24.11.2026") and their months ("Listopad 2026", "October 2026"): read one into a date and
the way it is written, and write any other date the same way. A robot picks a day in a
calendar by its name, as a person reads it.

A way of writing is a pattern of fields: ``{d}`` the day (``{dd}`` with a leading zero,
``{do}`` the English way: 1st, 24th), ``{m}``/``{mm}`` the month's number, ``{yyyy}`` the
year, ``{month}`` the month's name and ``{weekday}`` the day of the week, each in the language
and the case the calendar used (``{month}`` Polish genitive, ``{month_pl}`` Polish nominative,
``{month_en}`` English; a capital letter first, as in ``{Weekday_en}``, keeps the calendar's
capital letter). A name may say more around the date ("Choose ...", "..., selected"): the
pattern is the part that is the date.
"""

from __future__ import annotations

import re
from datetime import date

# The exported script carries this module from here on (export/playwright_py.py).

MONTHS: dict[str, list[str]] = {
    "month": [  # Polish, genitive: "24 listopada 2026"
        "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia",
        "września", "października", "listopada", "grudnia",
    ],
    "month_pl": [  # Polish, nominative: "Listopad 2026" over a calendar
        "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień",
        "wrzesień", "październik", "listopad", "grudzień",
    ],
    "month_en": [
        "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december",
    ],
    "month_en3": [  # "Nov 24, 2026", "Oct 2026"
        "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    ],
    "month_de": [
        "januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september",
        "oktober", "november", "dezember",
    ],
    "month_fr": [
        "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
        "octobre", "novembre", "décembre",
    ],
}  # fmt: skip
WEEKDAYS: dict[str, list[str]] = {
    "weekday": ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"],
    "weekday_en": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
    "weekday_en3": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    "weekday_de": ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"],
    "weekday_fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
}  # fmt: skip
_FIELD = re.compile(r"\{(\w+)\}")
_TOKENS = re.compile(r"[^\W\d_]+|\d+|[^\w\s]")
_ORDINALS = ("st", "nd", "rd", "th")
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")  # 2026-11-24
_NUMBERS = re.compile(r"(?<![\d.])(\d{1,2})([./-])(\d{1,2})\2(\d{4})(?!\d)")  # 24.11.2026


def _names(table: dict[str, list[str]], word: str) -> tuple[str, int] | None:
    """Which list (``month``, ``weekday_en``...) a word is in, and where."""
    for key, names in table.items():
        if word.lower() in names:
            return key, names.index(word.lower())
    return None


def _token(key: str, word: str) -> str:
    return "{" + (key[0].upper() + key[1:] if word[:1].isupper() else key) + "}"


def _year(word: str) -> int | None:
    return int(word) if len(word) == 4 and word.isdigit() and 1900 <= int(word) <= 2199 else None


def _day(words: list[str], at: int) -> tuple[int, str, int] | None:
    """A day of the month at ``words[at]`` ("24", "24th"): its number, its field and how many
    words it takes."""
    if at >= len(words) or not words[at].isdigit() or not 1 <= int(words[at]) <= 31:
        return None
    if at + 1 < len(words) and words[at + 1].lower() in _ORDINALS:
        return int(words[at]), "{do}", 2
    if at + 2 < len(words) and words[at + 1] == "." and _names(MONTHS, words[at + 2]):
        return int(words[at]), "{d}.", 2  # "24. Dezember 2026"
    return int(words[at]), "{dd}" if len(words[at]) == 2 and words[at][0] == "0" else "{d}", 1


def find_day(name: str) -> tuple[int, int, int | None, str] | None:
    """The first date in a name: (day, month, year or None, pattern); None when there is no
    date in it. The year may be left out ("24 listopada"): the calendar's month says it."""
    text = " ".join(name.split())
    iso = _ISO.search(text)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        return day, month, year, "{yyyy}-{mm}-{dd}"
    numbers = _NUMBERS.search(text)
    if numbers:
        first, sep, second, year_text = numbers.groups()
        if sep == "/" and int(second) > 12 >= int(first):  # 11/24/2026: the month first (US)
            fields = ("{m}", "{mm}", "{d}", "{dd}")
            day, month = int(second), int(first)
        elif sep == "/" and int(first) <= 12:
            return None  # 05/03/2027: the 5th of March or May the 3rd, the name cannot say
        else:
            fields = ("{d}", "{dd}", "{m}", "{mm}")
            day, month = int(first), int(second)
        lead = fields[1] if len(first) == 2 and first[0] == "0" else fields[0]
        then = fields[3] if len(second) == 2 and second[0] == "0" else fields[2]
        return day, month, int(year_text), f"{lead}{sep}{then}{sep}{{yyyy}}"
    words = _TOKENS.findall(text)
    for start in range(len(words)):
        found = _words_day(words, start)
        if found is not None:
            return found
    return None


def _words_day(words: list[str], start: int) -> tuple[int, int, int | None, str] | None:
    """A date written in words from ``words[start]`` on, with the day of the week before it
    if it is there ("wtorek, 24 listopada 2026", "Tuesday, November 24th, 2026")."""
    at, weekday = start, ""
    named = _names(WEEKDAYS, words[at])
    if named is not None:
        comma = at + 1 < len(words) and words[at + 1] == ","
        weekday = _token(named[0], words[at]) + (", " if comma else " ")
        at += 2 if comma else 1
    day = _day(words, at)
    if day is not None:  # 24 listopada 2026, 24th November 2026
        word = words[at + day[2]] if at + day[2] < len(words) else ""
        month = _names(MONTHS, word)
        if month is None:
            return None
        pattern = f"{weekday}{day[1]} {_token(month[0], word)}"
        then = at + day[2] + 1
        year = _year(words[then]) if then < len(words) else None
        return day[0], month[1] + 1, year, pattern + (" {yyyy}" if year else "")
    word = words[at] if at < len(words) else ""
    month = _names(MONTHS, word)
    dot = month is not None and at + 1 < len(words) and words[at + 1] == "."  # "Nov. 24"
    day = _day(words, at + 1 + dot) if month is not None else None
    if month is None or day is None:  # November 24, 2026
        return None
    pattern = f"{weekday}{_token(month[0], word)}{'.' if dot else ''} {day[1]}"
    then = at + 1 + dot + day[2]
    comma = then < len(words) and words[then] == ","
    after = then + 1 if comma else then
    year = _year(words[after]) if after < len(words) else None
    if year is not None:
        pattern += ", {yyyy}" if comma else " {yyyy}"
    return day[0], month[1] + 1, year, pattern


def read_day(name: str) -> tuple[date, str] | None:
    """The date a calendar's day stands for and the pattern its name is written in; None
    when the name holds no whole date."""
    found = find_day(name)
    if found is None or found[2] is None:
        return None
    return _date(found[2], found[1], found[0], found[3])


def read_month(text: str) -> tuple[int, int, str] | None:
    """A month as a calendar shows it over its days ("Listopad 2026", "October 2026",
    "11/2026"): (year, month, pattern); None when the text is not just a month."""
    words = _TOKENS.findall(" ".join(text.split()))
    if words[-2:] == ["r", "."]:  # "listopad 2026 r."
        words = words[:-2]
    if len(words) not in (2, 3):
        return None
    if _year(words[0]) is not None and words[1:2] == ["-"] and len(words) == 3:  # 2026-11
        if words[2].isdigit() and 1 <= int(words[2]) <= 12:
            return int(words[0]), int(words[2]), "{yyyy}-{mm}"
        return None
    year = _year(words[-1])
    if year is None:
        return None
    named = _names(MONTHS, words[0])
    if named is not None and (len(words) == 2 or words[1] == ","):  # Listopad 2026
        comma = "," if len(words) == 3 else ""
        return year, named[1] + 1, f"{_token(named[0], words[0])}{comma} {{yyyy}}"
    numbered = len(words) == 3 and words[1] in (".", "/", "-") and words[0].isdigit()
    if numbered and 1 <= int(words[0]) <= 12:  # 11/2026
        lead = "{mm}" if len(words[0]) == 2 else "{m}"
        return year, int(words[0]), f"{lead}{words[1]}{{yyyy}}"
    return None


ORACLE_MASK = "DD-MON-YYYY"
"""Oracle Forms' date mask: 01-NOV-2026 (benchmark D06, and programs built on Oracle Forms)."""
ORACLE_MASK_PL = "DD-MON-RRRR"
"""The same mask in an Oracle that speaks Polish (its date language): 01-LIS-2026, 31-PAŹ-2026
(benchmark M2: WCR)."""
_MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_MON_PL = ["STY", "LUT", "MAR", "KWI", "MAJ", "CZE", "LIP", "SIE", "WRZ", "PAŹ", "LIS", "GRU"]
_ORACLE = re.compile(r"(\d{1,2})-([^\W\d_]{3})-(\d{4})")


def oracle_date(day: date, mask: str = ORACLE_MASK) -> str:
    """A date in Oracle's mask: English months whatever the computer's language, or Polish ones
    for the Polish mask."""
    months = _MON_PL if mask == ORACLE_MASK_PL else _MON
    return f"{day.day:02d}-{months[day.month - 1]}-{day.year}"


def oracle_mask(text: str) -> str | None:
    """Which of Oracle's masks a date is written in (01-NOV-2026, 01-LIS-2026); None: neither.
    March is MAR in both: English, unless a Polish month shows otherwise."""
    found = _ORACLE.fullmatch(text.strip())
    if found is None:
        return None
    month = found.group(2).upper()
    if month in _MON:
        return ORACLE_MASK
    return ORACLE_MASK_PL if month in _MON_PL else None


def oracle_masks(text: str) -> list[str]:
    """Every Oracle mask a date can be written in: both for March (MAR), one for the others."""
    found = _ORACLE.fullmatch(text.strip())
    if found is None:
        return []
    month = found.group(2).upper()
    return [m for m, names in ((ORACLE_MASK, _MON), (ORACLE_MASK_PL, _MON_PL)) if month in names]


def read_oracle_date(text: str) -> date | None:
    """01-NOV-2026 or 01-LIS-2026 (any case) to a date; None when it is not one."""
    mask = oracle_mask(text)
    found = _ORACLE.fullmatch(text.strip())
    if mask is None or found is None:
        return None
    months = _MON_PL if mask == ORACLE_MASK_PL else _MON
    try:
        return date(
            int(found.group(3)), months.index(found.group(2).upper()) + 1, int(found.group(1))
        )
    except ValueError:
        return None


def same_way(first: str, second: str) -> bool:
    """Two patterns write dates the same way but for leading zeros ("05.03.2027" and
    "24.11.2026" are one calendar's names) and the language of the names of months and days
    ("Listopad 2026" over a calendar recorded in Polish, "November 2026" when it runs in
    English)."""

    def plain(pattern: str) -> str:
        pattern = pattern.replace("{dd}", "{d}").replace("{mm}", "{m}").lower()
        pattern = re.sub(r"\{month\w*\}", "{month}", pattern)
        return re.sub(r"\{weekday\w*\}", "{weekday}", pattern)

    return plain(first) == plain(second)


def _date(year: int, month: int, day: int, pattern: str) -> tuple[date, str] | None:
    try:
        return date(year, month, day), pattern
    except ValueError:
        return None


def _ordinal(day: int) -> str:
    suffix = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def day_name(day: date, pattern: str) -> str:
    """``day`` written as ``pattern`` (from ``read_day``) writes days."""

    def field(match: re.Match[str]) -> str:
        key = match.group(1)
        lower = key[0].lower() + key[1:]
        if lower in MONTHS:
            word = MONTHS[lower][day.month - 1]
        elif lower in WEEKDAYS:
            word = WEEKDAYS[lower][day.weekday()]
        else:
            return {
                "d": str(day.day),
                "dd": f"{day.day:02d}",
                "do": _ordinal(day.day),
                "m": str(day.month),
                "mm": f"{day.month:02d}",
                "yyyy": f"{day.year:04d}",
            }[key]
        return word[0].upper() + word[1:] if key[0].isupper() else word

    return _FIELD.sub(field, pattern)
