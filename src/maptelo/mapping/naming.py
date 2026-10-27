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
        "double": "{what} (dwuklikiem)",
        "each_row": "{what} w każdym wierszu tabeli „{table}”, w którym „{column}” nie jest puste",
        "calendar_by_person": (
            "Pole daty nie przyjmuje wpisywania, a robot programu Java nie wybiera jeszcze dat "
            "w kalendarzu: ten krok wykonuje pracownik."
        ),
        "fill": "Wypełnij pole „{field}”",
        "select": "Wybierz wartość z listy „{field}”",
        "choose": "Wypełnij pole „{field}” i wybierz podpowiedź",
        "open_row": "Otwórz wiersz, w którym {column} = {{{input}}}",
        "open_row_by": "Otwórz wiersz, w którym {rule}",
        "click": "Kliknij „{name}”",
        "beside": "Kliknij „…” przy polu „{field}”",
        "click_link": "Kliknij link „{name}”",
        "menu": "Wybierz z menu „{menu}” pozycję „{name}”",
        "row": "W tabeli „{table}” wybierz wiersz, w którym {rule}",
        "row_any": "W tabeli „{table}” wybierz wiersz",
        "row_command": "W tabeli „{table}” kliknij „{command}” w wierszu, w którym {rule}",
        "row_any_command": "W tabeli „{table}” kliknij „{command}” w wierszu",
        "row_first_command": "W tabeli „{table}” kliknij „{command}” w pierwszym wierszu "
        "(według „{column}”, {order})",
        "row_last_command": "W tabeli „{table}” kliknij „{command}” w ostatnim wierszu "
        "(według „{column}”, {order})",
        "row_first": "W tabeli „{table}” wybierz pierwszy wiersz (według „{column}”, {order})",
        "row_last": "W tabeli „{table}” wybierz ostatni wiersz (według „{column}”, {order})",
        "dialog": "W oknie „{dialog}” kliknij „{name}”",
        "holding": "Wybierz z listy pozycję zawierającą {values}",
        "dialog_holding": "W oknie „{dialog}” wybierz pozycję zawierającą {values}",
        "open_row_holding": "Otwórz wiersz, w którym „{column}” zawiera {values}",
        "and": " i ",
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
        "double": "{what} (double-click)",
        "each_row": "{what} in each row of the table “{table}” where “{column}” is not empty",
        "calendar_by_person": (
            "The date field takes no typing, and the Java robot does not pick dates in a "
            "calendar yet: a person does this step."
        ),
        "fill": "Fill in the “{field}” field",
        "select": "Choose a value from the “{field}” list",
        "choose": "Fill in the “{field}” field and pick the suggestion",
        "open_row": "Open the row where {column} = {{{input}}}",
        "open_row_by": "Open the row where {rule}",
        "click": "Click “{name}”",
        "beside": "Click “…” by the “{field}” field",
        "click_link": "Click the “{name}” link",
        "menu": "Choose “{name}” in the “{menu}” menu",
        "row": "In the “{table}” table, pick the row where {rule}",
        "row_any": "In the “{table}” table, pick a row",
        "row_command": "In the “{table}” table, click “{command}” in the row where {rule}",
        "row_any_command": "In the “{table}” table, click “{command}” in a row",
        "row_first_command": "In the “{table}” table, click “{command}” in the first row "
        "(by “{column}”, {order})",
        "row_last_command": "In the “{table}” table, click “{command}” in the last row "
        "(by “{column}”, {order})",
        "row_first": "In the “{table}” table, pick the first row (by “{column}”, {order})",
        "row_last": "In the “{table}” table, pick the last row (by “{column}”, {order})",
        "dialog": "In the “{dialog}” window, click “{name}”",
        "holding": "Choose the item of the list that holds {values}",
        "dialog_holding": "In the “{dialog}” window, choose the item that holds {values}",
        "open_row_holding": "Open the row whose “{column}” holds {values}",
        "and": " and ",
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


def day_shift(days: int, lang: Lang, *, working: bool = False) -> str:
    """'dzień wcześniej', '3 dni później' / 'the day before', '3 days after'; in working days:
    'ostatni dzień roboczy wcześniej', '2 dni robocze później' / 'the working day before'."""
    if working:
        if lang == "pl":
            if abs(days) == 1:
                return "ostatni dzień roboczy wcześniej" if days < 0 else "następny dzień roboczy"
            unit = (
                "dni robocze"
                if 2 <= abs(days) % 10 <= 4 and abs(days) // 10 != 1
                else "dni roboczych"
            )
            return f"{abs(days)} {unit} {'wcześniej' if days < 0 else 'później'}"
        if abs(days) == 1:
            return "the working day before" if days < 0 else "the next working day"
        return f"{abs(days)} working days {'before' if days < 0 else 'after'}"
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
