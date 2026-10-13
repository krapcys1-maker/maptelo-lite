"""Deterministic names: identifiers and step intents in Polish or English.

These are the fallback when no language model is used; they stay close to the screen
(„Wypełnij pole „CPN””, „Kliknij „Search””) because that is what a person can check against
it, and name the screen's words in quotes, never as part of the sentence („Wpisz Price”).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Literal

Lang = Literal["pl", "en"]

_POLISH = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def slug(text: str, max_length: int = 40) -> str:
    """Identifier: lowercase ascii letters, digits and underscores, starting with a letter."""
    ascii_text = (
        unicodedata.normalize("NFKD", text.translate(_POLISH))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    words = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    if not words or not words[0].isalpha():
        words = f"x_{words}" if words else "x"
    return words[:max_length].rstrip("_")


def unique(base: str, taken: set[str]) -> str:
    name, number = base, 2
    while name in taken:
        name = f"{base}_{number}"
        number += 1
    taken.add(name)
    return name


TEMPLATES: dict[Lang, dict[str, str]] = {
    "pl": {
        "open": "Otwórz ekran „{screen}”",
        "open_program": "Otwórz program „{program}”",
        "read": "Odczytaj wartość pola „{field}” na ekranie „{screen}”",
        "read_words": "Odczytaj wartość występującą po tekście „{words}” na ekranie „{screen}”",
        "read_area": "Odczytaj treść obszaru „{area}” na ekranie „{screen}”",
        "read_message": (
            "Odczytaj komunikat występujący po tekście „{words}:” na ekranie „{screen}”"
        ),
        "upload": "Załącz plik w polu „{field}”",
        "pick_date": "Wybierz datę w polu „{field}” z kalendarza",
        "fill": "Wypełnij pole „{field}”",
        "select": "Wybierz wartość z listy „{field}”",
        "choose": "Wypełnij pole „{field}” i wybierz podpowiedź",
        "open_row": "Otwórz wiersz, w którym {column} = {{{input}}}",
        "open_row_by": "Otwórz wiersz, w którym {rule}",
        "click": "Kliknij „{name}”",
        "click_link": "Kliknij link „{name}”",
        "menu": "Wybierz z menu „{menu}” pozycję „{name}”",
        "row": "W tabeli „{table}” wybierz wiersz, w którym {rule}",
        "row_any": "W tabeli „{table}” wybierz wiersz",
        "dialog": "W oknie „{dialog}” kliknij „{name}”",
        "press": "Naciśnij {keys}",
        "check": "Zaznacz „{name}”",
        "uncheck": "Odznacz „{name}”",
        "login": "Zalogowany użytkownik aplikacji {app}",
        "mapped_from": "Mapę utworzono automatycznie na podstawie nagrania z {date}.",
    },
    "en": {
        "open": "Open the “{screen}” screen",
        "open_program": "Open the “{program}” program",
        "read": "Read the value of the “{field}” field on the “{screen}” screen",
        "read_words": "Read the value that follows “{words}” on the “{screen}” screen",
        "read_area": "Read the text of the “{area}” area on the “{screen}” screen",
        "read_message": "Read the message that follows “{words}:” on the “{screen}” screen",
        "upload": "Attach a file in the “{field}” field",
        "pick_date": "Choose a date in the “{field}” field from the calendar",
        "fill": "Fill in the “{field}” field",
        "select": "Choose a value from the “{field}” list",
        "choose": "Fill in the “{field}” field and pick the suggestion",
        "open_row": "Open the row where {column} = {{{input}}}",
        "open_row_by": "Open the row where {rule}",
        "click": "Click “{name}”",
        "click_link": "Click the “{name}” link",
        "menu": "Choose “{name}” in the “{menu}” menu",
        "row": "In the “{table}” table, pick the row where {rule}",
        "row_any": "In the “{table}” table, pick a row",
        "dialog": "In the “{dialog}” window, click “{name}”",
        "press": "Press {keys}",
        "check": "Tick “{name}”",
        "uncheck": "Untick “{name}”",
        "login": "A user signed in to {app}",
        "mapped_from": "Map created automatically from the recording of {date}.",
    },
}


def say(lang: Lang, template: str, **values: str) -> str:
    return TEMPLATES[lang][template].format(**values)


_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")  # fmt: skip


def written_date(day: date, lang: Lang) -> str:
    """A day as a document in each language writes it: 12.10.2026 / 12 October 2026."""
    if lang == "pl":
        return f"{day.day:02d}.{day.month:02d}.{day.year}"
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


_VARYING_END = re.compile(r"\s*[-\u2013\u2014:]\s*\*$")


def human_title(title: str) -> str:
    """A window's title as a person says it: what changes from record to record (``*`` in a
    title kept as a template: a customer's code) left out at the end, an ellipsis inside
    (``Nowa wersja ceny - *`` -> ``Nowa wersja ceny``)."""
    shown = _VARYING_END.sub("", title).strip()
    return shown.replace("*", "…") if shown else title


def rows_noun(count: int, lang: Lang) -> str:
    """'1 wiersz', '2 wiersze', '5 wierszy' / '1 row', '2 rows'."""
    if lang == "en":
        return "row" if count == 1 else "rows"
    if count == 1:
        return "wiersz"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "wiersze"
    return "wierszy"


_COMPARISON: dict[Lang, dict[str, str]] = {
    "pl": {
        "gt": "więcej niż",
        "gte": "co najmniej",
        "lt": "mniej niż",
        "lte": "najwyżej",
        "eq": "",
    },
    "en": {"gt": "more than", "gte": "at least", "lt": "fewer than", "lte": "at most", "eq": ""},
}


def day_shift(days: int, lang: Lang) -> str:
    """'dzień wcześniej', '3 dni później' / 'the day before', '3 days after'."""
    if lang == "pl":
        if abs(days) == 1:
            return "dzień wcześniej" if days < 0 else "dzień później"
        return f"{abs(days)} dni {'wcześniej' if days < 0 else 'później'}"
    if abs(days) == 1:
        return "the day before" if days < 0 else "the day after"
    return f"{abs(days)} days {'before' if days < 0 else 'after'}"


def rows_phrase(table: str, where: dict[str, object], operator: str, count: int, lang: Lang) -> str:
    """'w tabeli „Price versions” jest więcej niż 1 wiersz z Status = Active'."""
    rule = (
        " i ".join(f"{k} = {v}" for k, v in where.items())
        if lang == "pl"
        else " and ".join(f"{k} = {v}" for k, v in where.items())
    )
    none = (operator in ("eq", "lte") and count == 0) or (operator == "lt" and count <= 1)
    if none:
        if lang == "pl":
            return f"w tabeli „{table}” nie ma wierszy" + (f" z {rule}" if rule else "")
        return f"the “{table}” table has no rows" + (f" with {rule}" if rule else "")
    words = _COMPARISON[lang][operator]
    amount = f"{words} {count}".strip()
    if lang == "pl":
        plural = rows_noun(count, lang) == "wiersze" and operator in ("eq", "gte", "lte")
        verb = "są" if plural else "jest"  # "są 2 wiersze", "jest więcej niż 2 wiersze"
        text = f"w tabeli „{table}” {verb} {amount} {rows_noun(count, lang)}"
        return text + (f" z {rule}" if rule else "")
    return f"the “{table}” table has {amount} {rows_noun(count, lang)}" + (
        f" with {rule}" if rule else ""
    )
