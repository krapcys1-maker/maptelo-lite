"""The map as a brief for a language model that is to build the automation (ai-brief.md and
ai-brief.json): what the process is for, where its values come from and how the screens want
them typed, every screen and what each of its buttons did, every step with all the ways of
finding its element and what happened after it, the decisions, the exceptions and the windows
that come by themselves, how to check the result, and what is not known yet.

A person reads the SOP and fills the gaps from what they know; a model reading this must not
have to: what the recordings did not show is listed as a question, never left to a guess.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from maptelo import PRODUCT, __version__
from maptelo.export.describe import (
    application_name,
    choice_text,
    documented,
    input_source,
    locator_text,
    predicate_text,
    quoted,
    records_text,
    rejection_lead,
    state_name,
    step_alternatives,
    step_rejections,
    step_success,
    type_name,
    window_texts,
)
from maptelo.export.effects import Effect, effect_text
from maptelo.mapping.naming import Lang
from maptelo.model.integrity import PLACEHOLDER, WHOLE_REF
from maptelo.model.schema import (
    Action,
    Executor,
    HttpVerifier,
    InputSpec,
    InputType,
    ProcessModel,
    RiskClass,
    ScreenVerifier,
    Step,
    WithinRow,
)
from maptelo.model.schema import Effect as ModelEffect

FORMAT = "maptelo-ai-brief/0.1"

ACTIONS: dict[Lang, dict[str, str]] = {
    "pl": {
        "navigate": "otwórz",
        "click": "kliknij",
        "fill": "wpisz",
        "select_option": "wybierz z listy",
        "check": "zaznacz",
        "uncheck": "odznacz",
        "press": "naciśnij klawisz",
        "read": "odczytaj",
        "wait": "poczekaj",
        "choose": "wpisz i wybierz podpowiedź",
        "upload": "dołącz plik",
        "download": "pobierz plik",
        "pick_date": "wybierz datę w kalendarzu",
    },
    "en": {
        "navigate": "open",
        "click": "click",
        "fill": "type",
        "select_option": "choose from the list",
        "check": "check",
        "uncheck": "uncheck",
        "press": "press the key",
        "read": "read",
        "wait": "wait",
        "choose": "type and pick the suggestion",
        "upload": "attach the file",
        "download": "download the file",
        "pick_date": "pick the date in the calendar",
    },
}

WORDS: dict[Lang, dict[str, str]] = {
    "pl": {
        "title": "Pakiet dla AI: {title}",
        "lead": (
            "Ten plik opisuje proces nagrany w programie {product}, tak aby model językowy (np. "
            "Claude) mógł zbudować z niego działającą automatyzację. Przekaż go razem z plikiem "
            "ai-brief.json i zrzutami z folderu images."
        ),
        "task": "Zadanie",
        "task_lines": (
            "Zbuduj automatyzację tego procesu i przestrzegaj poniższych zasad.\n"
            "1. Wykonuj kroki z części „Kroki” w podanej kolejności, raz dla każdego rekordu "
            "danych wejściowych (część „Dane wejściowe”).\n"
            "2. Element odnajduj sposobami z listy „Jak znaleźć element”, po kolei: weź "
            "pierwszy, który wskazuje dokładnie jeden element. Nie klikaj według współrzędnych "
            "ekranu.\n"
            "3. Po każdym kroku poczekaj na to, co opisuje „Co się dzieje po kroku” i "
            "„Oczekiwany wynik”, zanim wykonasz następny. Aplikacja bywa wolna: czekaj na znak, "
            "nie na stały czas.\n"
            "4. Kroki oznaczone „wykonuje pracownik” zostaw człowiekowi: zatrzymaj się przed "
            "nimi i przekaż sprawę.\n"
            "5. Gdy pojawi się okno lub komunikat z części „Wyjątki i okna, które pojawiają się "
            "same”, postąp tak, jak tam opisano. Okno albo komunikat, którego tam nie ma: "
            "zatrzymaj się i niczego nie zapisuj. Wyjątek: okno zgód na pliki cookie zamknij "
            "przyciskiem, który nie daje zgód ponad niezbędne („Tylko niezbędne”, „Odrzuć”), "
            "także gdy nagrania go nie pokazały, i pracuj dalej.\n"
            "6. Po zapisie sprawdź wynik sposobem z części „Jak sprawdzić wynik”. Dopiero wtedy "
            "rekord jest zrobiony.\n"
            "7. Każdy rekord zakończ jednym wynikiem: ZROBIONE (wynik sprawdzony), WYJĄTEK "
            "(reguła biznesowa nie pozwala), DO SPRAWDZENIA (coś mogło się zapisać, ale nie "
            "potwierdzono), BŁĄD (zatrzymano przed zapisem, nic się nie zmieniło).\n"
            "8. Nie zgaduj. Część „Czego nie wiemy” wymienia sprawy do ustalenia z właścicielem "
            "procesu przed pierwszym uruchomieniem.\n"
            "9. Wartości z ekranu porównuj z danymi tak, jak pokazuje je aplikacja: liczby jako "
            "liczby (ekran pokazuje np. „13 749,68 zł”: odstęp między tysiącami, przecinek "
            "dziesiętny i walutę; w danych to 13749.68), daty jako daty („01.11.2026” to "
            "2026-11-01), tekst bez względu na wielkość liter i powtórzone spacje. `{...}` w "
            "nazwie to dowolne słowa: „{...}{inputs.indeks}{...}{inputs.konto}{...}” to pozycja "
            "listy, która zawiera wartości indeksu i konta rekordu, w tej kolejności."
        ),
        "card": "Karta procesu",
        "goal": "Cel",
        "goal_unknown": "nieopisany (zob. „Czego nie wiemy”)",
        "story": "Opis procesu (słowami osoby, która go wykonuje)",
        "note_when": "Kiedy (słowami osoby nagrywającej)",
        "person_decides": "Tu decyduje człowiek (tak powiedziała osoba nagrywająca): automatyzacja "
        "zatrzymuje się przed tym krokiem i pyta człowieka",
        "choice": "Decyzja",
        "app": "Aplikacja",
        "web_app": "aplikacja WWW, adres {address}",
        "java_app": "program okienkowy w Javie, okno {window}",
        "records": "Dane",
        "records_person": "wartości podaje osoba albo program, który uruchamia proces",
        "writes": "Zapisuje dane",
        "writes_none": "żaden krok nie jest oznaczony jako zapis",
        "check": "Sprawdzenie wyniku",
        "check_none": "nieustalone (zob. „Czego nie wiemy”)",
        "verify_screen": "ekran programu: menu {menu}",
        "verify_page": "strona {url}",
        "verify_page_table": "strona {url}, tabela {table}",
        "verify_http": "odczyt przez API: {url}",
        "verify_row": "wiersz rekordu: {where}",
        "verify_expect": "ma pokazywać: {where}",
        "verify_answer": "odpowiedź (JSON): {where}",
        "verify_rows_all": "rekord zapisuje kilka wierszy: każdy z nich ma to pokazywać",
        "people": "Kroki człowieka",
        "people_none": "brak: robot może wykonać wszystkie kroki",
        "made_from": "Na podstawie",
        "steps_count": "Kroków",
        "env": "Środowisko i technologia",
        "web_env": (
            "Aplikacja WWW. Role i nazwy w „Jak znaleźć element” to role ARIA i nazwy "
            "dostępne dla czytników ekranu: odpowiadają lokatorom `get_by_role(role, name=…)` "
            "w Playwright. Dobrze sprawdzi się Playwright (Python lub TypeScript) albo Power "
            "Automate Desktop. Otwierając stronę, nie czekaj na jej pełne załadowanie (zdarzenie "
            "load, domyślne w `page.goto`): niektóre zasoby wczytują się bardzo długo. Czekaj na "
            'to, co opisuje „Oczekiwany wynik” (`wait_until="domcontentloaded"`, a potem na '
            "element)."
        ),
        "java_env": (
            "Program okienkowy w Javie. Jego elementy są dostępne przez Java Access Bridge "
            "(włączany poleceniem `jabswitch -enable` z katalogu bin Javy). Sprawdzą się np. "
            "biblioteka RPA.JavaAccessBridge (Python, RPA Framework) albo akcje automatyzacji "
            "interfejsu w Power Automate Desktop. Role w tym pliku to role ARIA; w Java Access "
            "Bridge nazywają się one tak:"
        ),
        "java_role": "Rola w tym pliku",
        "bridge_role": "Rola w Java Access Bridge",
        "address": "Adres startowy",
        "api_address": "Adres odczytu (API) do sprawdzenia wyniku",
        "window": "Tytuł okna programu",
        "locale": "Język i strefa czasowa",
        "inputs": "Dane wejściowe",
        "inputs_none": "Proces nie ma danych wejściowych.",
        "name": "Nazwa",
        "from": "Skąd",
        "kind": "Typ",
        "typed": "Jak wpisywać",
        "example": "Przykład",
        "required": "Wymagana",
        "yes": "tak",
        "no": "nie",
        "secret": "tajna, nie zapisuj jej w pliku",
        "choices": "jedna z: {choices}",
        "e_g": "np.",
        "pattern": "wzorzec: {pattern}",
        "per_line": "osobno dla każdej pozycji",
        "taken_after": "część wartości kolumny po „{separator}”",
        "written_as": "arkusz zapisuje datę jako `{pattern}`",
        "no_source": "nieznane",
        "screens": "Ekrany",
        "screen_known": "Rozpoznasz go po",
        "screen_used": "Elementy używane w procesie",
        "steps": "Kroki",
        "step": "Krok {n}: {intent}",
        "action": "Działanie",
        "value_input": "dana `{name}`",
        "value_const": "stała wartość {value}",
        "value_text": "tekst {value} (w miejsce {{…}} wstaw dane)",
        "value_saved": "wartość zapamiętana wcześniej (`{name}`)",
        "find": "Jak znaleźć element (po kolei)",
        "in_row": "W wierszu tabeli {table}, w którym {where}",
        "in_each_row": (
            "W każdym wierszu tabeli {table}, w którym {where}, po kolei (gdy takiego wiersza "
            "nie ma, krok nic nie robi)"
        ),
        "not_empty": "nie jest puste",
        "row_first": "pierwszym z pasujących",
        "row_last": "ostatnim z pasujących",
        "empty": "puste",
        "screen": "Ekran",
        "condition": "Warunek",
        "requires": "Warunek wstępny (w przeciwnym razie zatrzymaj się)",
        "otherwise": "Tylko wtedy, gdy nie wykonano kroku {n} (druga ścieżka)",
        "observed": "Co się dzieje po kroku (zaobserwowane w nagraniu)",
        "expected": "Oczekiwany wynik (sprawdź przed następnym krokiem)",
        "or_else": "Albo",
        "rejects": "Odrzucenie",
        "by": "Wykonuje",
        "robot": "robot",
        "person": "pracownik (zatrzymaj się i przekaż sprawę)",
        "commits": "ten krok zapisuje dane: nie powtarzaj go, jeśli nie wiesz, czy się udał",
        "irreversible": "ten krok jest nieodwracalny: wykonaj go tylko raz",
        "note": "Opis osoby nagrywającej",
        "picture": "Zrzut ekranu",
        "loop": "powtarzaj dla każdej pozycji rekordu",
        "select_either": (
            "Dana może być wartością opcji (value), jej widocznym tekstem albo kodem, od którego "
            "ten tekst się zaczyna (np. „C002 · Globex Retail S.A.” dla C002): wybierz opcję, "
            "która do niej pasuje (`select_option(dana)` w Playwright sprawdza wartość i tekst)."
        ),
        "timeout": "Czekaj najwyżej {seconds} s",
        "rules": "Decyzje, pętle i reguły",
        "rules_none": "Proces nie ma rozgałęzień: każdy rekord przechodzi te same kroki.",
        "rule_when": "Krok {n} ({intent}): tylko gdy {condition}",
        "rule_choice": "Krok {n} ({intent}): decyzja: {choice}",
        "rule_otherwise": "Krok {n} ({intent}): gdy nie wykonano kroku {other}",
        "rule_loop": "Kroki {steps}: dla każdej pozycji rekordu",
        "rule_row": "Krok {n} ({intent}): wiersz tabeli {table} wybierany regułą: {where}",
        "rule_each": (
            "Krok {n} ({intent}): pętla po wierszach tabeli {table}, w których {where}; przed "
            "każdym wierszem przeczytaj tabelę na nowo"
        ),
        "exceptions": "Wyjątki i okna, które pojawiają się same",
        "exceptions_none": "Nagrania nie pokazały wyjątków ani okien, które pojawiają się same.",
        "exception_line": "`{id}` ({kind}): {description}. Co zrobić: {todo}",
        "business": "reguła biznesowa",
        "system": "błąd techniczny",
        "retry": "spróbuj później jeszcze raz",
        "stop": "zatrzymaj się i zgłoś",
        "interrupt": "W dowolnej chwili: gdy {condition} → {actions}",
        "verify": "Jak sprawdzić wynik",
        "verify_none": "Nieustalone. Zob. „Czego nie wiemy”.",
        "unknown": "Czego nie wiemy (zapytaj właściciela procesu, nie zgaduj)",
        "unknown_none": "Nic: mapa odpowiada na wszystkie pytania potrzebne do automatyzacji.",
        "q_goal": "Jaki jest cel procesu i po czym poznać, że praca jest skończona?",
        "q_story": (
            "Jak przebiega proces opowiedziany własnymi słowami, jak nowej osobie w zespole: skąd "
            "są dane, co się robi w którym programie, co bywa inaczej?"
        ),
        "q_why": "Po co są kroki bez opisu: {steps}?",
        "q_why_more": "{steps} i {more} innych",
        "q_data": (
            "Skąd biorą się dane wejściowe (arkusz, e-mail, portal) i ile rekordów jest zwykle "
            "naraz?"
        ),
        "q_scope": "Co robot może zrobić sam, a co zostaje u człowieka (decyzje, akceptacje)?",
        "q_failures": (
            "Co czasem idzie nie tak (błąd programu, brak danych, wyjątek) i co wtedy robisz?"
        ),
        "q_never": (
            "Czego robot nie może zrobić nigdy (np. zatwierdzić własnego wniosku, zapisać dwa "
            "razy)?"
        ),
        "c_data": "Skąd dane",
        "c_scope": "Zakres",
        "c_done": "Kiedy gotowe",
        "c_failures": "Co bywa nie tak i co wtedy",
        "c_never": "Czego nie robić nigdy",
        "q_verify": (
            "Jak niezależnie sprawdzić wynik (np. lista, w której widać zapisany rekord, albo "
            "odczyt z API)?"
        ),
        "q_source": "Skąd brać wartość `{name}` ({description})?",
        "q_person": (
            "Krok {n} ({intent}) wykonuje pracownik: czy robot może go wykonać, i według jakiej "
            "reguły?"
        ),
        "q_choice": (
            "Krok {n} ({intent}): kiedy wybierasz „{chosen}”, a kiedy {others}? Podaj regułę "
            "słowami (np. w opisie kroku). Maptelo Lite tworzy mapę "
            "z jednego nagrania i nie łączy nagrań; robi to pełne Maptelo. "
            "Bez reguły automatyzacja zatrzymuje "
            "się przed tym krokiem."
        ),
        "q_one": (
            "Mapa powstała z jednego nagrania, czyli jednego przypadku. Jakie inne przypadki "
            "się zdarzają (inne dane, błędy, wyjątki) i co wtedy?"
        ),
        "q_one_rows": (
            "Mapa robi każdy wiersz arkusza osobno, bo nagranie pokazało rekord z jednego "
            "wiersza. Czy rekord bywa kilkoma wierszami (np. pozycje jednego zamówienia)? Jeśli "
            "tak, nagraj przypadek z kilkoma wierszami (mapa z takiego nagrania powtarza "
            "pozycje) albo opisz słowami, po których kolumnach poznać wiersze jednego rekordu i "
            "które kroki powtarza się dla każdej pozycji. Do tego czasu nie wykonuj wierszy, "
            "których sprawdzenie wyniku nie odróżnia od siebie."
        ),
        "files": "Pliki",
        "file_json": "ai-brief.json: ta sama treść w postaci do odczytu przez program",
        "file_model": "model.yaml: model procesu {product} (jego kroki, dane i reguły)",
        "file_images": "images/: zrzuty ekranu każdego kroku z zaznaczonym elementem",
        "generated": "Wygenerowano w programie",
    },
    "en": {
        "title": "AI brief: {title}",
        "lead": (
            "This file describes a process recorded with {product}, so that a language model "
            "(e.g. Claude) can build a working automation from it. Pass it on together with "
            "ai-brief.json and the screenshots in the images folder."
        ),
        "task": "Task",
        "task_lines": (
            "Build an automation of this process and keep to these rules.\n"
            "1. Do the steps of “Steps” in their order, once for each record of the inputs "
            "(“Inputs”).\n"
            "2. Find each element with the ways listed under “How to find the element”, in "
            "order: take the first that points at exactly one element. Never click by screen "
            "coordinates.\n"
            "3. After each step wait for what “What happens after the step” and “Expected "
            "result” describe before the next one. The application can be slow: wait for the "
            "sign, not for a fixed time.\n"
            "4. Leave the steps marked “done by a person” to a person: stop before them and "
            "hand the case over.\n"
            "5. When a window or a message listed under “Exceptions and windows that come by "
            "themselves” appears, do what it says. A window or message not listed there: stop "
            "and save nothing. Except a window asking for cookie consents: close it with the "
            "button that gives no consent beyond what is needed (“Only necessary”, “Reject”), "
            "even when no recording showed it, and go on.\n"
            "6. After saving, check the result as “How to check the result” says. Only then is "
            "the record done.\n"
            "7. End every record with one outcome: DONE (result checked), EXCEPTION (a business "
            "rule does not allow it), TO CHECK (something may have been saved but it is not "
            "confirmed), ERROR (stopped before saving, nothing changed).\n"
            "8. Do not guess. “What is not known” lists what to settle with the process owner "
            "before the first run.\n"
            "9. Compare values on the screen with the inputs as the application shows them: "
            "numbers as numbers (a screen may show “13 749,68 zł”: a space between thousands, a "
            "decimal comma and the currency; in the inputs that is 13749.68), dates as dates "
            "(“01.11.2026” is 2026-11-01), text regardless of letter case and repeated spaces. "
            "`{...}` in a name is any words: “{...}{inputs.indeks}{...}{inputs.konto}{...}” is "
            "the item of a list that holds the record's item and account, in this order."
        ),
        "card": "Process card",
        "goal": "Goal",
        "goal_unknown": "not described (see “What is not known”)",
        "story": "The process (in the words of the person who does it)",
        "note_when": "When (in the words of the person recording)",
        "person_decides": "A person decides here (the person recording said so): the automation "
        "stops before this step and asks a person",
        "choice": "Decision",
        "app": "Application",
        "web_app": "web application at {address}",
        "java_app": "Java desktop program, window {window}",
        "records": "Data",
        "records_person": "the values come from the person or program that starts the process",
        "writes": "Saves data",
        "writes_none": "no step is marked as saving",
        "check": "Checking the result",
        "check_none": "not settled (see “What is not known”)",
        "verify_screen": "the program's screen: menu {menu}",
        "verify_page": "the page {url}",
        "verify_page_table": "the page {url}, table {table}",
        "verify_http": "read through the API: {url}",
        "verify_row": "the record's row: {where}",
        "verify_expect": "it shows: {where}",
        "verify_answer": "the answer (JSON): {where}",
        "verify_rows_all": "the record writes several rows: each of them shows it",
        "people": "Steps of a person",
        "people_none": "none: a robot can do every step",
        "made_from": "Made from",
        "steps_count": "Steps",
        "env": "Environment and technology",
        "web_env": (
            "A web application. The roles and names under “How to find the element” are ARIA "
            "roles and accessible names: they match Playwright's `get_by_role(role, name=…)`. "
            "Playwright (Python or TypeScript) or Power Automate Desktop will do. When opening a "
            "page, do not wait for it to load in full (the load event, `page.goto`'s default): "
            "some resources take very long. Wait for what “Expected result” says "
            '(`wait_until="domcontentloaded"`, then for the element).'
        ),
        "java_env": (
            "A Java desktop program. Its elements are reached through the Java Access Bridge "
            "(turned on with `jabswitch -enable` from Java's bin folder). RPA.JavaAccessBridge "
            "(Python, RPA Framework) or Power Automate Desktop's UI automation will do. The "
            "roles in this file are ARIA roles; the Java Access Bridge calls them:"
        ),
        "java_role": "Role in this file",
        "bridge_role": "Role in the Java Access Bridge",
        "address": "Start address",
        "api_address": "Address of the read API (to check the result)",
        "window": "Title of the program's window",
        "locale": "Language and time zone",
        "inputs": "Inputs",
        "inputs_none": "The process has no inputs.",
        "name": "Name",
        "from": "Source",
        "kind": "Type",
        "typed": "How to type it",
        "example": "Example",
        "required": "Required",
        "yes": "yes",
        "no": "no",
        "secret": "secret, never write it to a file",
        "choices": "one of: {choices}",
        "e_g": "e.g.",
        "pattern": "pattern: {pattern}",
        "per_line": "for each line separately",
        "taken_after": "the part of the column's value after “{separator}”",
        "written_as": "the sheet writes the date as `{pattern}`",
        "no_source": "not known",
        "screens": "Screens",
        "screen_known": "Recognised by",
        "screen_used": "Elements the process uses",
        "steps": "Steps",
        "step": "Step {n}: {intent}",
        "action": "Action",
        "value_input": "input `{name}`",
        "value_const": "the fixed value {value}",
        "value_text": "the text {value} (put the inputs in place of {{…}})",
        "value_saved": "a value kept from an earlier step (`{name}`)",
        "find": "How to find the element (in order)",
        "in_row": "In the row of the table {table} where {where}",
        "in_each_row": (
            "In each row of the table {table} where {where}, one after another (with no such "
            "row the step does nothing)"
        ),
        "not_empty": "is not empty",
        "row_first": "the first that matches",
        "row_last": "the last that matches",
        "empty": "empty",
        "screen": "Screen",
        "condition": "Condition",
        "requires": "Precondition (otherwise stop)",
        "otherwise": "Only when step {n} was not done (the other way)",
        "observed": "What happens after the step (seen in the recording)",
        "expected": "Expected result (check it before the next step)",
        "or_else": "Or",
        "rejects": "Rejection",
        "by": "Done by",
        "robot": "the robot",
        "person": "a person (stop and hand the case over)",
        "commits": "this step saves data: do not repeat it unless you know it failed",
        "irreversible": "this step cannot be undone: do it once",
        "note": "What the person recording said",
        "picture": "Screenshot",
        "loop": "repeat for each line of the record",
        "select_either": (
            "The input may be the option's value, its visible text, or the code its text starts "
            "with (e.g. “C002 · Globex Retail S.A.” for C002): choose the option that matches it "
            "(Playwright's `select_option(value)` checks the value and the text)."
        ),
        "timeout": "Wait at most {seconds} s",
        "rules": "Decisions, loops and rules",
        "rules_none": "The process has no branches: every record goes through the same steps.",
        "rule_when": "Step {n} ({intent}): only when {condition}",
        "rule_choice": "Step {n} ({intent}): a decision: {choice}",
        "rule_otherwise": "Step {n} ({intent}): when step {other} was not done",
        "rule_loop": "Steps {steps}: for each line of the record",
        "rule_row": "Step {n} ({intent}): the row of the table {table} chosen by the rule: {where}",
        "rule_each": (
            "Step {n} ({intent}): a loop over the rows of the table {table} where {where}; read "
            "the table again before each row"
        ),
        "exceptions": "Exceptions and windows that come by themselves",
        "exceptions_none": (
            "The recordings showed no exceptions and no windows that come by themselves."
        ),
        "exception_line": "`{id}` ({kind}): {description}. What to do: {todo}",
        "business": "a business rule",
        "system": "a technical error",
        "retry": "try again later",
        "stop": "stop and report",
        "interrupt": "At any moment: when {condition} → {actions}",
        "verify": "How to check the result",
        "verify_none": "Not settled. See “What is not known”.",
        "unknown": "What is not known (ask the process owner, do not guess)",
        "unknown_none": "Nothing: the map answers every question an automation needs.",
        "q_goal": "What is the process for, and how does one know the work is done?",
        "q_story": (
            "How does the process go, told in one's own words as to someone new on the team: "
            "where the data comes from, what is done in which program, what goes otherwise?"
        ),
        "q_why": "What are the steps without a description for: {steps}?",
        "q_why_more": "{steps} and {more} more",
        "q_data": (
            "Where do the inputs come from (a sheet, a mail, a portal), and how many records at "
            "a time?"
        ),
        "q_scope": (
            "What may a robot do by itself, and what stays with a person (decisions, approvals)?"
        ),
        "q_failures": (
            "What goes wrong at times (a program error, missing data, an exception), and what "
            "do you do then?"
        ),
        "q_never": "What must a robot never do (approve its own request, save twice)?",
        "c_data": "Where the data come from",
        "c_scope": "Scope",
        "c_done": "When it is done",
        "c_failures": "What goes wrong, and what then",
        "c_never": "Never do",
        "q_verify": (
            "How can the result be checked independently (a list that shows the saved record, "
            "a read through an API)?"
        ),
        "q_source": "Where does the value `{name}` ({description}) come from?",
        "q_person": "Step {n} ({intent}) is done by a person: may a robot do it, and by what rule?",
        "q_choice": (
            "Step {n} ({intent}): when do you choose “{chosen}”, and when {others}? Give the rule "
            "in words (in the step's description, say). Maptelo Lite maps "
            "one recording and joins no recordings; the full Maptelo does. "
            "Without a rule the automation "
            "stops before this step."
        ),
        "q_one": (
            "The map is made from one recording, that is one case. What other cases happen "
            "(other data, errors, exceptions), and what then?"
        ),
        "q_one_rows": (
            "The map does each row of the sheet on its own: the recording showed a record of "
            "one row. Is a record sometimes several rows (the lines of one order)? If so, record "
            "a case of several rows (the map of that recording repeats the lines), or say in "
            "words which columns tell the rows of one record and which steps are repeated for "
            "each line. Until then, do not run rows that the check of the result cannot tell "
            "apart."
        ),
        "files": "Files",
        "file_json": "ai-brief.json: the same content for a program to read",
        "file_model": (
            "model.yaml: the {product} model of the process (its steps, inputs and rules)"
        ),
        "file_images": "images/: a screenshot of each step with its element marked",
        "generated": "Generated with",
    },
}


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _numbers(model: ProcessModel) -> dict[str, int]:
    return {step.id: n for n, step in enumerate(model.steps, start=1)}


def value_text(step: Step, lang: Lang) -> str | None:
    """What the step types or chooses: an input, a fixed value, a text with inputs in it."""
    w = WORDS[lang]
    value = step.value
    if value is None or step.action in (Action.NAVIGATE, Action.CLICK, Action.READ):
        return None
    if isinstance(value, str):
        whole = WHOLE_REF.match(value)
        if whole is not None:
            key = "value_input" if whole.group(1) == "inputs" else "value_saved"
            return w[key].format(name=whole.group(2))
        if PLACEHOLDER.search(value):
            shown = PLACEHOLDER.sub(lambda m: "{" + m.group(2) + "}", value)
            return w["value_text"].format(value=quoted(shown, lang))
    return w["value_const"].format(value=quoted(str(value), lang))


def where_text(
    where: Mapping[str, object], lang: Lang, where_not: Mapping[str, object] | None = None
) -> str:
    w = WORDS[lang]
    parts = []
    for column, value in where.items():
        if value is None:
            parts.append(f"{quoted(column, lang)} = {w['empty']}")
            continue
        parts.append(f"{quoted(column, lang)} = {_rule_value(value, lang)}")
    for column, value in (where_not or {}).items():
        if value is None:  # the rows that show something there (an error)
            parts.append(f"{quoted(column, lang)} {w['not_empty']}")
            continue
        parts.append(f"{quoted(column, lang)} ≠ {_rule_value(value, lang)}")
    return ", ".join(parts)


def _rule_value(value: object, lang: Lang) -> str:
    shown = str(value)
    whole = WHOLE_REF.match(shown)
    return f"`{whole.group(2)}`" if whole is not None else quoted(shown, lang)


def verify_lines(effect: ModelEffect, lang: Lang, api: str | None = None) -> list[str]:
    """How the result is checked, in full: where it is read (``api``: the read API's address, a
    path of the read is under it), the record's row by its values, what the row shows, and
    whether the record wrote several rows."""
    w = WORDS[lang]
    verifier = effect.verifier
    if isinstance(verifier, HttpVerifier):
        url = verifier.url
        if api and not url.startswith(("http://", "https://")):
            url = api.rstrip("/") + "/" + url.lstrip("/")
        lines = [w["verify_http"].format(url=f"`{url}`")]
        lines.append(w["verify_answer"].format(where=where_text(verifier.expect, lang)))
        return lines
    if isinstance(verifier, ScreenVerifier):
        menu = " > ".join(quoted(item, lang) for item in verifier.menu)
        lines = [w["verify_screen"].format(menu=menu)]
    else:
        url = f"`{verifier.url}`"
        lines = [
            w["verify_page_table"].format(url=url, table=quoted(verifier.table, lang))
            if verifier.table
            else w["verify_page"].format(url=url)
        ]
    lines.append(w["verify_row"].format(where=where_text(verifier.row, lang)))
    if verifier.expect:
        lines.append(w["verify_expect"].format(where=where_text(verifier.expect, lang)))
    if getattr(verifier, "rows", "one") == "all":
        lines.append(w["verify_rows_all"])
    return lines


def row_text(within: WithinRow, lang: Lang) -> str:
    w = WORDS[lang]
    table = within.table[0]
    name = quoted(table.name, lang) if table.name else locator_text(table, lang)
    where = where_text(within.where, lang, within.where_not) or "—"
    text = w["in_each_row" if within.pick == "each" else "in_row"].format(table=name, where=where)
    if within.pick == "first":
        text += f" ({w['row_first']})"
    elif within.pick == "last":
        text += f" ({w['row_last']})"
    return text


_MAPPED = re.compile(r"(Mapę utworzono automatycznie|Map created automatically)[^.]*\.(\d+\.)*\s*")
"""The sentence a single recording's map adds to its description (mapping.naming)."""


def goal(model: ProcessModel) -> str:
    """What the process is for: as its people said it (the card), else as its description says
    it (not the map's own sentence)."""
    if model.card is not None and (model.card.goal or "").strip():
        return (model.card.goal or "").strip()
    return _MAPPED.sub("", model.description or "").strip()


def open_questions(
    model: ProcessModel, lang: Lang, *, notes: Sequence[str] = (), one_recording: bool = False
) -> list[str]:
    """What the map does not know and an automation needs: asked, never guessed."""
    w = WORDS[lang]
    numbers = _numbers(model)
    found = [str(note) for note in notes]
    said = model.card.answered() if model.card is not None else {}
    if "story" not in said:
        found.append(w["q_story"])
    if not goal(model):
        found.append(w["q_goal"])
    if "data" not in said and model.records is None and model.inputs:
        found.append(w["q_data"])
    if "scope" not in said:
        found.append(w["q_scope"])
    if "failures" not in said:
        found.append(w["q_failures"])
    if "never" not in said:
        found.append(w["q_never"])
    for name, spec in model.inputs.items():
        if spec.column is None and spec.derived is None and not spec.secret:
            found.append(w["q_source"].format(name=name, description=spec.description or name))
    mark = "„{}”" if lang == "pl" else "“{}”"
    for step in model.steps:
        if step.executor is Executor.HUMAN and step.alternatives and step.note_when:
            continue  # the person said when: the step's „When” is the rule to confirm
        if step.executor is Executor.HUMAN and step.alternatives:  # a decision, its rule unknown
            chosen = next((t.name for t in step.target or [] if t.name), None) or step.intent
            others = ", ".join(mark.format(o) for o in step.alternatives)
            numbered = {"n": numbers[step.id], "intent": step.intent}
            found.append(w["q_choice"].format(chosen=chosen, others=others, **numbered))
        elif step.executor is Executor.HUMAN:
            found.append(w["q_person"].format(n=numbers[step.id], intent=step.intent))
    silent = [
        f"{numbers[s.id]} ({s.intent})"
        for s in model.steps
        if not s.note and s.action is not Action.NAVIGATE
    ]
    if silent:  # why they are done is what no recording shows
        listed = ", ".join(silent[:8])
        if len(silent) > 8:
            listed = w["q_why_more"].format(steps=listed, more=len(silent) - 8)
        found.append(w["q_why"].format(steps=listed))
    if not model.effects and "done" not in said:
        found.append(w["q_verify"])
    if one_recording:
        found.append(w["q_one"])
        columns = [spec.column for spec in model.inputs.values() if spec.column]
        if model.records is not None and not model.records.one_run_per and len(columns) > 1:
            found.append(w["q_one_rows"])  # Lite maps one recording: what joins rows, it asks
    return list(dict.fromkeys(found))


def render_ai_brief(
    model: ProcessModel,
    *,
    lang: Lang = "pl",
    notes: Sequence[str] = (),
    images: Mapping[str, str] | None = None,
    effects: Mapping[str, Sequence[Effect]] | None = None,
    source: str | None = None,
    one_recording: bool = False,
) -> str:
    """``effects``: what each step did in its recording (export.effects); ``one_recording``:
    the map is made from a single recording (one case: its rules are not known)."""
    images = images or {}
    effects = effects or {}
    model = documented(model)
    w = WORDS[lang]
    numbers = _numbers(model)
    app = model.application
    java = app.kind == "java"
    out = [
        f"# {w['title'].format(title=model.title)}",
        "",
        f"> {w['lead'].format(product=PRODUCT)}",
        "",
    ]

    out += [f"## {w['task']}", "", w["task_lines"], ""]

    # -- the process card
    writes = [
        s for s in model.steps if s.effective_risk in (RiskClass.COMMIT, RiskClass.IRREVERSIBLE)
    ]
    people = [s for s in model.steps if s.executor is Executor.HUMAN]
    purpose = goal(model) or w["goal_unknown"]
    where = (
        w["java_app"].format(window=quoted(app.window or app.name, lang))
        if java
        else w["web_app"].format(address=app.base_url or "—")
    )
    out += [f"## 1. {w['card']}", ""]
    story = model.card.story.strip() if model.card is not None and model.card.story else ""
    if story:  # the process in the words of the person who does it: what to read first
        out.append(f"- **{w['story']}:** {story}")
    out.append(f"- **{w['goal']}:** {purpose}")
    out.append(f"- **{w['app']}:** {application_name(app)} ({where})")
    said = model.card.answered() if model.card is not None else {}
    out.append(f"- **{w['records']}:** {records_text(model, lang) or w['records_person']}")
    for key in ("data", "scope", "done", "failures", "never"):
        if key in said:
            out.append(f"- **{w['c_' + key]}:** {said[key]}")
    out.append(f"- **{w['steps_count']}:** {len(model.steps)}")
    saved = ", ".join(f"{numbers[s.id]} ({s.intent})" for s in writes) or w["writes_none"]
    out.append(f"- **{w['writes']}:** {saved}")
    checked = "; ".join(e.description for e in model.effects) or w["check_none"]
    out.append(f"- **{w['check']}:** {checked}")
    by_people = ", ".join(f"{numbers[s.id]} ({s.intent})" for s in people) or w["people_none"]
    out.append(f"- **{w['people']}:** {by_people}")
    if source:
        out.append(f"- **{w['made_from']}:** {source}")
    if model.preconditions:
        out += [f"- {p}" for p in model.preconditions]
    out.append("")

    # -- environment
    out += [f"## 2. {w['env']}", ""]
    if java:
        out.append(f"- **{w['window']}:** {quoted(app.window or app.name, lang)}")
    elif app.base_url:
        out.append(f"- **{w['address']}:** {app.base_url}")
    if app.api_base_url:
        out.append(f"- **{w['api_address']}:** {app.api_base_url}")
    if app.locale or app.timezone:
        out.append(f"- **{w['locale']}:** {', '.join(x for x in (app.locale, app.timezone) if x)}")
    out += ["", w["java_env" if java else "web_env"], ""]
    if java:
        out += [f"| {w['java_role']} | {w['bridge_role']} |", "|---|---|"]
        for aria, bridge in _bridge_roles(model).items():
            out.append(f"| {aria} | {', '.join(bridge)} |")
        out.append("")

    # -- inputs
    out += [f"## 3. {w['inputs']}", ""]
    if not model.inputs:
        out += [w["inputs_none"], ""]
    else:
        out += [
            "| "
            + " | ".join(w[k] for k in ("name", "from", "kind", "typed", "example", "required"))
            + " |"
        ]
        out.append("|---|---|---|---|---|---|")
        for name, spec in model.inputs.items():
            src = (
                input_source(spec, lang).split(", ")[0]
                if spec.column or spec.derived
                else w["no_source"]
            )
            how = []
            if spec.taken_after:  # 5510 of „CENNIK_ZK_5510”
                how.append(w["taken_after"].format(separator=spec.taken_after))
            if spec.written_as:  # Excel's 46327 in a CSV file, 15/November/2026
                how.append(w["written_as"].format(pattern=spec.written_as))
            if spec.typed_as:
                typed = _typed_example(spec)
                how.append(
                    f"`{spec.typed_as}`" + (f" ({w['e_g']} {quoted(typed, lang)})" if typed else "")
                )
            if spec.choices:
                how.append(w["choices"].format(choices=", ".join(spec.choices)))
            if spec.pattern:
                how.append(w["pattern"].format(pattern=f"`{spec.pattern}`"))
            if spec.per_line:
                how.append(w["per_line"])
            if spec.secret:
                how.append(w["secret"])
            example = "" if spec.example is None or spec.secret else spec.example
            required = w["yes"] if spec.required else w["no"]
            cells = [
                f"`{name}`",
                src,
                type_name(lang, spec.type),
                "; ".join(how),
                example,
                required,
            ]
            out.append("| " + " | ".join(_cell(c) for c in cells) + " |")
        out.append("")

    # -- screens
    if model.states:
        out += [f"## 4. {w['screens']}", ""]
        for state_id, state in model.states.items():
            out += [f"### {state_name(model, state_id)} (`{state_id}`)", ""]
            if state.visible:
                known = ", ".join(locator_text(v, lang) for v in state.visible)
                out.append(f"- **{w['screen_known']}:** {known}")
            used = [s for s in model.steps if s.in_state == state_id and s.target]
            if used:
                out.append(f"- **{w['screen_used']}:**")
                for step in used:
                    assert step.target is not None
                    did = "; ".join(effect_text(e, lang) for e in effects.get(step.id, ()))
                    done = ACTIONS[lang][step.action.value]
                    line = f"  - {locator_text(step.target[0], lang)} → {done}"
                    out.append(line + (f": {did}" if did else ""))
            out.append("")

    # -- steps
    out += [f"## 5. {w['steps']}", ""]
    for step in model.steps:
        n = numbers[step.id]
        out += [f"### {w['step'].format(n=n, intent=step.intent)}", ""]
        action = ACTIONS[lang][step.action.value]
        if step.action is Action.NAVIGATE and isinstance(step.value, str) and not java:
            action += f" {step.value}"
        if step.action is Action.PRESS and isinstance(step.value, str):
            action += f" {step.value}"
        value = value_text(step, lang)
        out.append(f"- **{w['action']}:** {action}" + (f" — {value}" if value else ""))
        if step.action is Action.SELECT_OPTION and value and not java and step.match != "words":
            # benchmark M7 r7: scripts chose the chain „K0017” by the options' text, never found
            out.append(f"- {w['select_either']}")
        if step.per_line:
            out.append(f"- ↻ {w['loop']}")
        if step.in_state:
            out.append(f"- **{w['screen']}:** {quoted(state_name(model, step.in_state), lang)}")
        if step.target:
            out.append(f"- **{w['find']}:**")
            out += [
                f"  {k}. {locator.describe()}" for k, locator in enumerate(step.target, start=1)
            ]
        if step.within is not None:
            out.append(f"- {row_text(step.within, lang)}")
        if step.when is not None:
            out.append(f"- **{w['condition']}:** {predicate_text(step.when, model, lang)}")
        if step.requires is not None:
            out.append(f"- **{w['requires']}:** {predicate_text(step.requires, model, lang)}")
        if step.otherwise is not None:
            out.append(f"- {w['otherwise'].format(n=numbers.get(step.otherwise, '?'))}")
        out += [f"- {text}" for text in window_texts(step, model, lang)]
        seen = effects.get(step.id, ())
        if seen:
            out.append(f"- **{w['observed']}:** " + "; ".join(effect_text(e, lang) for e in seen))
        success = step_success(step, model, lang)
        if success:
            out.append(f"- **{w['expected']}:** {success}")
        out += [f"- **{w['or_else']}:** {other}" for other in step_alternatives(step, model, lang)]
        for exception_id, description in step_rejections(step, model):
            lead = rejection_lead(step, exception_id, lang)
            out.append(f"- **{w['rejects']}:** {lead} *{description}* → `{exception_id}`")
        if step.timeout_s:
            out.append(f"- {w['timeout'].format(seconds=f'{step.timeout_s:g}')}")
        out.append(
            f"- **{w['by']}:** {w['person'] if step.executor is Executor.HUMAN else w['robot']}"
        )
        if step.effective_risk is RiskClass.IRREVERSIBLE:
            out.append(f"- ⚑ {w['irreversible']}")
        elif step.effective_risk is RiskClass.COMMIT:
            out.append(f"- ⚑ {w['commits']}")
        if step.note:
            out.append(f"- **{w['note']}:** {step.note}")
        if step.note_when:
            out.append(f"- **{w['note_when']}:** {step.note_when}")
        if step.person_decides:
            out.append(f"- ⚑ {w['person_decides']}")
        if (choice := choice_text(step, model, lang)) is not None:
            out.append(f"- ⚑ **{w['choice']}:** {choice}")
        if step.id in images:
            out.append(f"- **{w['picture']}:** ![{n}. {step.intent}]({images[step.id]})")
        out.append("")

    # -- decisions, loops, rules
    out += [f"## 6. {w['rules']}", ""]
    rules = []
    looped = [numbers[s.id] for s in model.steps if s.per_line]
    if looped:
        rules.append(w["rule_loop"].format(steps=", ".join(str(n) for n in looped)))
    for step in model.steps:
        n = numbers[step.id]
        if step.when is not None:
            condition = predicate_text(step.when, model, lang)
            rules.append(w["rule_when"].format(n=n, intent=step.intent, condition=condition))
        if (choice := choice_text(step, model, lang)) is not None:
            rules.append(w["rule_choice"].format(n=n, intent=step.intent, choice=choice))
        if step.otherwise is not None:
            rules.append(
                w["rule_otherwise"].format(
                    n=n, intent=step.intent, other=numbers.get(step.otherwise, "?")
                )
            )
        if step.within is not None and (step.within.where or step.within.where_not):
            table = step.within.table[0]
            name = quoted(table.name, lang) if table.name else locator_text(table, lang)
            rule = where_text(step.within.where, lang, step.within.where_not)
            if step.within.pick in ("first", "last"):
                rule += f" ({w['row_first' if step.within.pick == 'first' else 'row_last']})"
            key = "rule_each" if step.within.pick == "each" else "rule_row"
            rules.append(w[key].format(n=n, intent=step.intent, table=name, where=rule))
    out += [f"- {r}" for r in rules] if rules else [w["rules_none"]]
    out.append("")

    # -- exceptions and interrupts
    out += [f"## 7. {w['exceptions']}", ""]
    lines = []
    for exception_id, exception in model.exceptions.items():
        todo = w["retry"] if exception.is_retryable else w["stop"]
        kind = w["business"] if exception.kind.value == "business" else w["system"]
        lines.append(
            w["exception_line"].format(
                id=exception_id, kind=kind, description=exception.description, todo=todo
            )
        )
    for interrupt in model.interrupts:
        actions = ", ".join(
            f"{ACTIONS[lang][a.action.value]} "
            f"{quoted(a.target[0].name or a.target[0].describe(), lang)}"
            if a.target
            else ACTIONS[lang].get(a.action.value, a.action.value)
            for a in interrupt.do
        )
        condition = predicate_text(interrupt.when, model, lang)
        lines.append(w["interrupt"].format(condition=condition, actions=actions))
    out += [f"- {line}" for line in lines] if lines else [w["exceptions_none"]]
    out.append("")

    # -- verification
    out += [f"## 8. {w['verify']}", ""]
    if model.effects:
        for effect in model.effects:
            out.append(f"- **{effect.id}**: {effect.description}")
            api = model.application.api_base_url
            out += [f"  - {line}" for line in verify_lines(effect, lang, api)]
    else:
        out.append(w["verify_none"])
    out.append("")

    # -- what is not known
    out += [f"## 9. {w['unknown']}", ""]
    asked = open_questions(model, lang, notes=notes, one_recording=one_recording)
    out += [f"- {q}" for q in asked] if asked else [w["unknown_none"]]
    out.append("")

    out += [f"## {w['files']}", ""]
    out += [
        f"- {w['file_json']}",
        f"- {w['file_model'].format(product=PRODUCT)}",
        f"- {w['file_images']}",
        "",
    ]
    out.append(f"*{w['generated']} {PRODUCT} {__version__}.*")
    return "\n".join(out) + "\n"


def ai_brief_data(
    model: ProcessModel,
    *,
    lang: Lang = "pl",
    notes: Sequence[str] = (),
    images: Mapping[str, str] | None = None,
    effects: Mapping[str, Sequence[Effect]] | None = None,
    one_recording: bool = False,
) -> dict[str, Any]:
    """The brief for a program: the model as it is, what each step did, the screenshots and the
    open questions."""
    return {
        "format": FORMAT,
        "language": lang,
        "process": model.model_dump(mode="json", by_alias=True, exclude_none=True),
        "observed": {
            step_id: [e.as_dict() for e in found] for step_id, found in (effects or {}).items()
        },
        "images": dict(images or {}),
        "open_questions": open_questions(model, lang, notes=notes, one_recording=one_recording),
    }


def _typed_example(spec: InputSpec) -> str | None:
    """The example as people type it (01-LIS-2026 for 2026-11-01, K0010% for K0010)."""
    if spec.example is None or spec.secret:
        return None
    value: Any = spec.example
    if spec.typed_as and "{}" in spec.typed_as and isinstance(value, str):
        before, after = spec.typed_as.split("{}", 1)
        if value.startswith(before) and value.endswith(after):
            return value  # the example as it was typed („Account 604217359”, K0010%)
    try:
        if spec.type is InputType.DATE and isinstance(value, str):
            value = date.fromisoformat(value)
        elif spec.type is InputType.DECIMAL and not isinstance(value, Decimal):
            value = Decimal(str(value))
        return spec.on_screen(value)
    except (ValueError, ArithmeticError, TypeError):
        return None


def _bridge_roles(model: ProcessModel) -> dict[str, list[str]]:
    """The ARIA roles the model's steps use, with the Java Access Bridge's names for them."""
    from maptelo.desktop.screen import ARIA_ROLE

    used = {
        locator.role
        for step in model.steps
        for locator in [*(step.target or ()), *(step.within.table if step.within else ())]
        if locator.role
    }
    bridge: dict[str, list[str]] = {}
    for java_role, aria in ARIA_ROLE.items():
        if aria in used:
            bridge.setdefault(aria, []).append(java_role)
    return dict(sorted(bridge.items()))
