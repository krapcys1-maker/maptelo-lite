"""Studio speaks Polish; Maptelo's core and command line speak English. What the core says
on its way to the page is translated here, by the shape of the sentence: what a sentence
names (a step, a value, an address, an exception, a file) is kept as it is, and a sentence
inside another (a reason, a detail) is translated in turn. A sentence not known here stays
in English rather than becoming something it does not say; a test lists every sentence the
core can say and fails when one has no Polish yet.
"""

from __future__ import annotations

import re
from functools import cache

SENTENCES: list[tuple[str, str]] = [
    # an address the browser cannot open
    ("cannot open {where}: {problem}", "nie da się otworzyć {where}: {problem}"),
    # a Java program through the Java Access Bridge
    ("the Java program does not answer (a window it opened may be waiting)",
     "program Java nie odpowiada (może czekać okno, które otworzył)"),
    ("the Java program still does not answer (a window it opened may be waiting)",
     "program Java nadal nie odpowiada (może czekać okno, które otworzył)"),
    ("no {dll} or {other} in the Java folders", "nie ma {dll} ani {other} w folderach Javy"),
    ("the Java here has only {dll} ({bits}-bit), which this {own}-bit Python cannot load, and "
     "no Python of its bitness was found to load it: install Maptelo again (it brings one "
     "along) or Python 3.12 of that bitness for this user",
     "Java na tym komputerze ma tylko {dll} ({bits} bity), którego ten Python ({own} bity) nie "
     "załaduje, a nie znaleziono Pythona tej samej bitowości, który mógłby go załadować: "
     "zainstaluj ponownie Maptelo (zawiera taki Python) albo zainstaluj dla tego "
     "użytkownika Pythona 3.12 o tej bitowości"),
    ("starting the helper Python {python}", "uruchamianie pomocniczego Pythona {python}"),
    ("the helper Python {python} does not start: {reason}",
     "pomocniczy Python {python} nie uruchamia się: {reason}"),
    ("the helper of the Java Access Bridge ended{words}",
     "proces pomocniczy Java Access Bridge zakończył działanie{words}"),
    ("the Java Access Bridge could not start: {reason}",
     "Java Access Bridge nie mógł wystartować: {reason}"),
    ("the Java Access Bridge did not start ({reason})",
     "Java Access Bridge nie wystartował ({reason})"),
    ("the Java Access Bridge works on Windows only", "Java Access Bridge działa tylko w Windows"),
    ("cannot work on the desktop {desktop}", "nie da się pracować na pulpicie {desktop}"),
    ("window {window} does not answer through the bridge",
     "okno {window} nie odpowiada przez most"),
    ("window {window} has no accessible root", "okno {window} nie ma korzenia dostępności"),
    ("the element at {path} is gone (window changed)",
     "element pod {path} zniknął (okno się zmieniło)"),
    ("{role} {name} is no longer there ({other} instead)",
     "{role} {name} już tam nie ma (jest {other})"),
    # a date picked in a calendar
    ("the calendar shows no days", "kalendarz nie pokazuje dni"),
    ("the calendar did not move towards “{wanted}”",
     "kalendarz nie przesunął się w stronę „{wanted}”"),
    ("the day “{wanted}” cannot be picked in the calendar",
     "dnia „{wanted}” nie da się wybrać w kalendarzu"),
    ("the calendar shows the month, but no day “{wanted}” to click",
     "kalendarz pokazuje ten miesiąc, ale nie ma w nim dnia „{wanted}” do kliknięcia"),
    ("the calendar cannot be moved towards “{wanted}”",
     "kalendarza nie da się przesunąć w stronę „{wanted}”"),
    ("the calendar did not reach “{wanted}”", "kalendarz nie doszedł do „{wanted}”"),
    # the browser
    ("the profile {folder} is in use by another Maptelo browser: wait for it to finish, "
     "or use another profile",
     "profil {folder} jest używany przez inną przeglądarkę Maptelo: poczekaj, aż skończy, "
     "albo użyj innego profilu"),
    ("the profile {folder} cannot be opened: {reason}",
     "nie da się otworzyć profilu {folder}: {reason}"),
    # inputs
    ("{value} is below the minimum {limit}", "{value} jest poniżej minimum {limit}"),
    ("{value} is above the maximum {limit}", "{value} jest powyżej maksimum {limit}"),
    ("expected text, got {value}", "oczekiwano tekstu, jest {value}"),
    ("{value} does not match the pattern {pattern}", "{value} nie pasuje do wzorca {pattern}"),
    ("{value} is not one of: {choices}", "{value} nie jest jedną z wartości: {choices}"),
    ("expected an integer, got {value}", "oczekiwano liczby całkowitej, jest {value}"),
    ("expected a number, got {value}", "oczekiwano liczby, jest {value}"),
    ("expected a finite number, got {value}", "oczekiwano skończonej liczby, jest {value}"),
    ("expected a date as YYYY-MM-DD, got {value}", "oczekiwano daty RRRR-MM-DD, jest {value}"),
    ("expected true/false, got {value}", "oczekiwano tak/nie (true/false), jest {value}"),
    # sheets
    ("{file} is not a workbook: it has no sheets", "{file} to nie skoroszyt: nie ma arkuszy"),
    ("{file} cannot be read as a workbook: {reason}",
     "{file} nie da się odczytać jako skoroszytu: {reason}"),
    ("{file} has no sheet '{sheet}' (sheets: {sheets})",
     "{file} nie ma arkusza „{sheet}” (arkusze: {sheets})"),
    # IT's policy
    ("IT's policy {path} cannot be read: {reason}",
     "nie da się odczytać zasad IT {path}: {reason}"),
    ("IT's policy {path} is not valid: {reason}", "zasady IT {path} są niepoprawne: {reason}"),
    ("AI is turned off by IT's policy ({path})", "AI jest wyłączone przez zasady IT ({path})"),
    ("IT's policy allows AI only at {endpoint} ({path})",
     "zasady IT dopuszczają AI tylko pod adresem {endpoint} ({path})"),
    # Maptelo Lite: a demonstration and its map, no robot
    ("the full Maptelo runs processes: Maptelo Lite only maps them",
     "procesy uruchamia pełne Maptelo: Maptelo Lite tylko je mapuje"),
    ("there is no recording {name} of {key}", "nie ma nagrania {name} procesu {key}"),
    # a demonstration in a Java program, recorded from Studio
    ("a Java program can be recorded on Windows only",
     "program Java można nagrać tylko w Windows"),
    ("the Java program “{program}” is not open, or the Java Access Bridge is off for it: IT "
     "turns it on with jabswitch -enable, then the program is started again",
     "program Java „{program}” nie jest otwarty albo most Java (Java Access Bridge) jest dla "
     "niego wyłączony: dział IT włącza go poleceniem jabswitch -enable, potem program trzeba "
     "uruchomić ponownie"),
    # Studio's own checks of a request
    ("there is no such file or folder", "nie ma takiego pliku ani folderu"),
    ("there is no such file", "nie ma takiego pliku"),
    ("there is no such job", "nie ma takiego zadania"),
    ("there is no process {name}", "nie ma procesu {name}"),
    ("the description is empty", "opis jest pusty"),
    ("a step is described while its recording runs",
     "opis kroku dodaje się w trakcie jego nagrywania"),
    ("which step: its first action's number", "który krok: numer jego pierwszego działania"),
    ("which step: its action's number", "który krok: numer jego działania"),
    ("the card: its answers by question", "karta procesu: odpowiedzi na kolejne pytania"),
    ("there is no map of the recording {recording} of {key}",
     "nie ma mapy nagrania {recording} procesu {key}"),
    ("{name} is still in use (Windows says {code}); "
     "close its preview or the program using its files and try again",
     "Pliki nagrania {name} są nadal używane (kod Windows: {code}). "
     "Zamknij ich podgląd lub program, który je otworzył, i spróbuj ponownie."),
    ("{name} could not be deleted (Windows says {code})",
     "nie udało się usunąć {name} (Windows zgłasza kod {code})"),
    ("the file is empty", "plik jest pusty"),
    ("the file is larger than 50 MB", "plik ma więcej niż 50 MB"),
    ("the language is pl or en", "język to pl albo en"),
    ("{title} is still running", "wciąż trwa: {title}"),
    ("the process needs a name with letters or digits, e.g. Ceny klientów",
     "proces potrzebuje nazwy z literami albo cyframi, np. Ceny klientów"),
    ("the profile name must be small letters, digits, - or _ (up to 64), e.g. praca",
     "nazwa profilu: małe litery, cyfry, - albo _ (do 64 znaków), np. praca"),
    ("the address must start with http:// or https://",
     "adres musi zaczynać się od http:// albo https://"),
    ("the browser must be one of: {names}", "przeglądarka musi być jedną z: {names}"),
    ("a profile keeps the sign-in itself: choose a profile or a session",
     "profil sam pamięta logowanie: wybierz profil albo plik sesji"),
    ("there is no session file {name}", "nie ma pliku sesji {name}"),
    ("there is no sheet {name}", "nie ma arkusza {name}"),
    ("'{name}' must be text", "„{name}” musi być tekstem"),
    ("a sheet must be one of: {suffixes}", "arkusz musi mieć jedno z rozszerzeń: {suffixes}"),
    ("{path} is outside the workspace", "{path} jest poza folderem roboczym"),
]  # fmt: skip

SENTENCE_SLOTS = {
    "message",
    "detail",
    "reason",
    "problem",
    "problems",
    "tried",
    "how",
    "refusal",
    "checked",
}
"""Slots that hold a sentence of their own, translated in turn; the others name things."""
_SLOT = re.compile(r"\\\{(\w+)\\\}")


def _whole(english: str) -> bool:
    """A sentence tried before a text is split at "; ": it has "; " inside it, or a slot
    that holds several sentences joined that way."""
    return "; " in english or "{problems}" in english


@cache
def _rules() -> tuple[list[tuple[re.Pattern[str], str]], list[tuple[re.Pattern[str], str]]]:
    """(whole sentences, the others): the first are tried before a text is split into its
    sentences, the others after, so no slot swallows the next sentence."""
    compiled = [
        (re.compile(_SLOT.sub(lambda m: f"(?P<{m.group(1)}>.*?)", re.escape(english))), pl)
        for english, pl in SENTENCES
    ]
    pairs = list(zip(compiled, SENTENCES, strict=True))
    return (
        [rule for rule, (english, _) in pairs if _whole(english)],
        [rule for rule, (english, _) in pairs if not _whole(english)],
    )


def _apply(text: str, rules: list[tuple[re.Pattern[str], str]]) -> str | None:
    for pattern, template in rules:
        found = pattern.fullmatch(text)
        if found is not None:
            slots = {
                name: polish(value) if name in SENTENCE_SLOTS else value
                for name, value in found.groupdict().items()
            }
            return template.format(**slots)
    return None


def polish(text: str) -> str:
    """The sentence in Polish when its shape is known; else as it is (in English)."""
    joined, single = _rules()
    whole = _apply(text, joined)
    if whole is not None:
        return whole
    if "; " in text:  # several sentences in one
        parts = text.split("; ")
        translated = [polish(part) for part in parts]
        if translated != parts:
            return "; ".join(translated)
    whole = _apply(text, single)
    if whole is not None:
        return whole
    head, colon, rest = text.partition(": ")
    if colon:  # "<a step>: <what went wrong>"
        after = polish(rest)
        if after != rest:
            return head + colon + after
    return text


def polish_all(texts: list[str]) -> list[str]:
    return [polish(text) for text in texts]
