"""Plain-language descriptions of model parts, shared by every document exporter."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from maptelo.mapping.naming import Lang, day_shift, human_title, rows_phrase
from maptelo.model.schema import (
    Action,
    Application,
    Executor,
    FieldCheck,
    InputSpec,
    InputType,
    Locator,
    Predicate,
    ProcessModel,
    Step,
    ValueCheck,
)

WORDS: dict[Lang, dict[str, str]] = {
    "pl": {
        "process": "Proces",
        "application": "aplikacja",
        "source": "nagranie",
        "sources": "nagrania",
        "version": "wersja",
        "preconditions": "Wymagania wstępne",
        "card": "Cel i zakres",
        "card_story": "Opis procesu",
        "card_goal": "Cel",
        "card_data": "Skąd dane",
        "card_scope": "Zakres",
        "card_done": "Kiedy gotowe",
        "card_failures": "Co bywa nie tak i co wtedy",
        "card_never": "Czego nie robić nigdy",
        "inputs": "Dane wejściowe",
        "source_column": "Skąd",
        "per_row": "Dla każdego wiersza arkusza „{sheet}” ({file}): jeden przebieg na wiersz.",
        "from_column": "kolumna „{column}”",
        "counted_from": "liczona z {base}: {shift}",
        "typed_as": "wpisywana jako {pattern}",
        "input": "Nazwa",
        "type": "Typ",
        "description": "Opis",
        "example": "Przykład",
        "steps": "Kroki",
        "diagram": "Diagram",
        "exceptions": "Sytuacje wyjątkowe",
        "exception": "Wyjątek",
        "kind": "Rodzaj",
        "what_to_do": "Co zrobić",
        "business": "biznesowy",
        "system": "techniczny",
        "stop_and_report": "przerwij i zgłoś",
        "retry": "spróbuj ponownie",
        "interrupts": "Przerwania (mogą pojawić się w dowolnym momencie)",
        "to_confirm": "Do potwierdzenia",
        "verification": "Jak sprawdzić wynik",
        "no_effects": (
            "Mapa nie określa jeszcze, jak niezależnie sprawdzić wynik procesu (np. odczytem "
            "z systemu). Należy to ustalić przed automatyzacją procesu."
        ),
        "expected": "Oczekiwany wynik",
        "person_note": "Opis",
        "person_when": "Kiedy",
        "person_decides": "Tu decyduje człowiek (tak powiedziała osoba nagrywająca)",
        "choice": "Decyzja",
        "choice_person": "nagrania pokazują tylko „{chosen}”, choć {where} jest też {others}. "
        "Kiedy wybrać inaczej, nie wiadomo: decyduje człowiek",
        "choice_said": "nagrania pokazują tylko „{chosen}”, choć {where} jest też {others}. Kiedy "
        "wybrać „{chosen}”, mówi osoba nagrywająca (zob. „Kiedy”); gdy jej słowa nie pozwalają "
        "rozstrzygnąć, decyduje człowiek",
        "choice_rule": "„{chosen}” tylko wtedy, gdy {rule}. W pozostałych przypadkach zatrzymaj "
        "się przed tym krokiem i przekaż sprawę człowiekowi: nagrania nie pokazują, kiedy wybrać "
        "{others}",
        "choice_always": "{where} jest też {others}, ale właściciel procesu potwierdził, że "
        "zawsze wybiera się „{chosen}”",
        "choice_row": "w wierszu tabeli",
        "choice_screen": "na ekranie",
        "if_message": "Jeśli pojawi się komunikat",
        "if_shown": "Jeśli widać",
        "then_stop": "przerwij",
        "value": "wartość",
        "read_in_step": "odczytana w kroku",
        "named_in_step": "opcja, którą wymienia tekst odczytany w kroku",
        "from_picture": (
            "Z obrazu dokumentu: wartość w postaci wydrukowanej; robot odczytuje ją modelem "
            "rozpoznającym obrazy i weryfikuje regułami ({checks}); niepewny odczyt przekazuje "
            "do weryfikacji pracownikowi"
        ),
        "each_line": "Dla każdej pozycji rekordu (każdego jego wiersza w arkuszu):",
        "per_line_input": "na pozycję",
        "file": "plik",
        "downloaded_in_step": "pobrany w kroku",
        "keep_typed": "Gdy żadna podpowiedź nie pasuje: zostaw wpisaną wartość i przejdź dalej",
        "address": "adres",
        "only_if": "Warunek",
        "otherwise": "Wykonaj tylko wtedy, gdy nie wykonano kroku {step} (ścieżka alternatywna)",
        "requires": "Warunek wstępny kroku (spełniony we wszystkich nagraniach)",
        "or_stop": "w przeciwnym razie przerwij",
        "in_window": "W osobnym oknie",
        "opens_window": "Otwiera osobne okno; kolejne kroki wykonuje się w nim",
        "closes_window": "Zamyka okno; kolejne kroki wykonuje się w oknie poniżej",
        "opens_last": "Otwiera osobne okno",
        "closes_last": "Zamyka okno",
        "asks_confirm": "Przeglądarka pyta {message}: {answer}",
        "asks_prompt": "Przeglądarka prosi {message}: wpisz {value} i kliknij OK",
        "shows_alert": "Przeglądarka wyświetla {message}: kliknij OK",
        "cancel": "Anuluj",
        "other_question": "Inne pytanie przeglądarki: kliknij Anuluj i przerwij proces",
        "commits": "zapisuje dane",
        "by_person": "wykonuje pracownik",
        "control": (
            "kontrola: pracownik porównuje dane z dokumentem przed zatwierdzeniem "
            "(zasada czterech oczu)"
        ),
        "screen": "ekran",
        "message_appears": "pojawia się komunikat",
        "dialog_appears": "pojawia się okno",
        "field_appears": "pojawia się",
        "no_error": "brak komunikatu błędu",
        "or_else": "Albo",
        "confirmed_by": "potwierdzenie",
        "page_path": "adres strony pasuje do",
        "start": "Start",
        "end": "Koniec",
        "result": "Wynik?",
        "warnings": "Ostrzeżenia",
        "model_source": "Model (YAML)",
        "string": "tekst",
        "integer": "liczba całkowita",
        "decimal": "liczba",
        "date": "data",
        "boolean": "tak/nie",
        "generated": "Wygenerowano w programie",
        "click": "kliknij",
    },
    "en": {
        "process": "Process",
        "application": "application",
        "source": "recording",
        "sources": "recordings",
        "version": "version",
        "preconditions": "Preconditions",
        "card": "Goal and scope",
        "card_story": "The process",
        "card_goal": "Goal",
        "card_data": "Where the data come from",
        "card_scope": "Scope",
        "card_done": "When it is done",
        "card_failures": "What goes wrong, and what then",
        "card_never": "Never do",
        "inputs": "Inputs",
        "source_column": "Source",
        "per_row": "For each row of the sheet “{sheet}” ({file}): one run per row.",
        "from_column": "column “{column}”",
        "counted_from": "counted from {base}: {shift}",
        "typed_as": "typed as {pattern}",
        "input": "Name",
        "type": "Type",
        "description": "Description",
        "example": "Example",
        "steps": "Steps",
        "diagram": "Diagram",
        "exceptions": "Exceptions",
        "exception": "Exception",
        "kind": "Kind",
        "what_to_do": "What to do",
        "business": "business",
        "system": "technical",
        "stop_and_report": "stop and report",
        "retry": "retry",
        "interrupts": "Interruptions (can appear at any time)",
        "to_confirm": "To confirm",
        "verification": "How to check the result",
        "no_effects": (
            "The map does not yet define how to check the result of the process "
            "independently (e.g. by reading it back from the system). Define it before "
            "automating the process."
        ),
        "expected": "Expected result",
        "person_note": "Description",
        "person_when": "When",
        "person_decides": "A person decides here (the person recording said so)",
        "choice": "Decision",
        "choice_person": "the recordings show only “{chosen}”, although {where} also offers "
        "{others}. When to choose otherwise is not known: a person decides",
        "choice_said": "the recordings show only “{chosen}”, although {where} also offers "
        "{others}. When to choose “{chosen}” the person recording said (see “When”); where their "
        "words do not settle it, a person decides",
        "choice_rule": "“{chosen}” only when {rule}. In other cases stop before this step and "
        "hand the case to a person: the recordings do not show when to choose {others}",
        "choice_always": "{where} also offers {others}, but the process owner confirmed that "
        "“{chosen}” is chosen every time",
        "choice_row": "the table's row",
        "choice_screen": "the screen",
        "if_message": "If the message appears",
        "if_shown": "If the screen shows",
        "then_stop": "stop",
        "value": "value",
        "read_in_step": "read in step",
        "named_in_step": "the option named in the text read in step",
        "from_picture": (
            "From the document image: the value as printed; the robot reads it with an image "
            "recognition model and verifies it by rules ({checks}); an uncertain reading is "
            "passed to an employee for review"
        ),
        "each_line": "For each line of the record (each of its rows in the sheet):",
        "per_line_input": "per line",
        "file": "file",
        "downloaded_in_step": "downloaded in step",
        "keep_typed": "If no suggestion matches: keep the entered value and continue",
        "address": "address",
        "only_if": "Only if",
        "otherwise": "Only if step {step} was not performed (alternative path of the process)",
        "requires": "Precondition of the step (met in all recordings)",
        "or_stop": "otherwise stop",
        "in_window": "In the separate window",
        "opens_window": "Opens a separate window; the next steps are performed in it",
        "closes_window": "Closes the window; the next steps are performed in the window below",
        "opens_last": "Opens a separate window",
        "closes_last": "Closes the window",
        "asks_confirm": "The browser asks {message}: {answer}",
        "asks_prompt": "The browser asks {message}: enter {value} and click OK",
        "shows_alert": "The browser displays {message}: click OK",
        "cancel": "Cancel",
        "other_question": "Any other browser question: click Cancel and stop the process",
        "commits": "saves data",
        "by_person": "performed by an employee",
        "control": (
            "control: an employee compares the data with the document before approving "
            "(four-eyes principle)"
        ),
        "screen": "screen",
        "message_appears": "a message appears",
        "dialog_appears": "a window appears",
        "field_appears": "appears",
        "no_error": "no error message",
        "or_else": "Or",
        "confirmed_by": "confirmed by",
        "page_path": "page address matches",
        "start": "Start",
        "end": "End",
        "result": "Result?",
        "warnings": "Warnings",
        "model_source": "Model (YAML)",
        "string": "text",
        "integer": "whole number",
        "decimal": "number",
        "date": "date",
        "boolean": "yes/no",
        "generated": "Generated with",
        "click": "click",
    },
}


def records_text(model: ProcessModel, lang: Lang) -> str | None:
    """The table the inputs come from, row by row (M7)."""
    if model.records is None:
        return None
    sheet = model.records.sheet or "1"
    return word(lang, "per_row").format(sheet=sheet, file=model.records.description or "—")


def input_source(spec: InputSpec, lang: Lang) -> str:
    """Where an input comes from: its column, and how it is typed on screen; a date counted
    from another one says from which."""
    if spec.derived is not None:
        shift = day_shift(spec.derived.days, lang)
        text = word(lang, "counted_from").format(base=spec.derived.from_, shift=shift)
        if spec.typed_as:
            text += ", " + word(lang, "typed_as").format(pattern=spec.typed_as)
        return text
    if spec.column is None:
        return ""
    text = word(lang, "from_column").format(column=spec.column)
    if spec.typed_as:
        text += ", " + word(lang, "typed_as").format(pattern=spec.typed_as)
    return text


def application_name(app: Application) -> str:
    """The application as text: its name, or its address when the name is only the host
    it was recorded on (its pages did not say what it is called)."""
    host = urlsplit(app.base_url).hostname if app.base_url else None
    if app.name in (host, "localhost", "application"):
        return f"the application at {app.base_url}" if app.base_url else "the application"
    return app.name


def word(lang: Lang, key: str) -> str:
    return WORDS[lang][key]


def type_name(lang: Lang, kind: InputType) -> str:
    return word(lang, kind.value)


def locator_text(locator: Locator, lang: Lang = "pl") -> str:
    if locator.role is not None and locator.name:
        return f"{locator.role} {quoted(locator.name, lang)}"
    return locator.role if locator.role is not None else locator.describe()


def quoted(text: str, lang: Lang) -> str:
    """A name from the application, quoted as each language does: „Zapisz” / “Save”."""
    return f"„{text}”" if lang == "pl" else f"“{text}”"


def state_name(model: ProcessModel, state_id: str) -> str:
    state = model.states.get(state_id)
    if state is None:
        return state_id
    if state.description:
        return state.description
    if state.visible:
        first = state.visible[0]
        return first.name or first.describe()
    return state_id


ROLE_NOUNS: dict[Lang, dict[str, str]] = {
    "pl": {
        "textbox": "pole",
        "searchbox": "pole",
        "spinbutton": "pole",
        "combobox": "lista",
        "listbox": "lista",
        "list": "lista",
        "listitem": "pozycja listy",
        "option": "opcja",
        "button": "przycisk",
        "link": "link",
        "checkbox": "pole wyboru",
        "radio": "przycisk opcji",
        "switch": "przełącznik",
        "table": "tabela",
        "grid": "tabela",
        "cell": "komórka",
        "gridcell": "komórka",
        "columnheader": "nagłówek kolumny",
        "heading": "nagłówek",
        "row": "wiersz",
        "tab": "karta",
        "menuitem": "pozycja menu",
        "status": "komunikat",
        "alert": "komunikat",
        "definition": "wartość",
        "img": "obraz",
        "paragraph": "tekst",
        "region": "obszar",
        "group": "grupa",
    },
    "en": {
        "textbox": "field",
        "searchbox": "field",
        "spinbutton": "field",
        "combobox": "list",
        "listbox": "list",
        "button": "button",
        "link": "link",
        "checkbox": "checkbox",
        "table": "table",
        "heading": "heading",
        "row": "row",
    },
}

STRATEGY_NOUNS: dict[Lang, dict[str, str]] = {
    "pl": {
        "field": "pole",
        "label": "pole",
        "placeholder": "pole",
        "text": "tekst",
        "submits": "przycisk",
        "action": "przycisk",
    },
    "en": {"field": "field", "label": "field", "placeholder": "field", "submits": "button"},
}
"""What an element found by other means than its role is, in words (an element found by the
name its form sends, „price”, is a field: never „pojawia się field” in a Polish SOP)."""


_NOT_SEEN = {  # what is not seen, in Polish: "nie widać pola", "nie widać okna"
    "pole": "pola",
    "lista": "listy",
    "pozycja listy": "pozycji listy",
    "opcja": "opcji",
    "przycisk": "przycisku",
    "link": "linku",
    "pole wyboru": "pola wyboru",
    "przycisk opcji": "przycisku opcji",
    "przełącznik": "przełącznika",
    "tabela": "tabeli",
    "komórka": "komórki",
    "nagłówek kolumny": "nagłówka kolumny",
    "nagłówek": "nagłówka",
    "wiersz": "wiersza",
    "karta": "karty",
    "pozycja menu": "pozycji menu",
    "komunikat": "komunikatu",
    "wartość": "wartości",
    "obraz": "obrazu",
    "tekst": "tekstu",
    "obszar": "obszaru",
    "grupa": "grupy",
    "element": "elementu",
}


def element_noun(locator: Locator, lang: Lang) -> str:
    """What the element is, in words: by its role, else by how it is found (a field by the name
    its form sends), else „element”."""
    if locator.role is not None:
        return ROLE_NOUNS[lang].get(locator.role, locator.role if lang == "en" else "element")
    return STRATEGY_NOUNS[lang].get(locator.strategy, "element")


def element_absent(locator: Locator, lang: Lang) -> str:
    """'nie widać komunikatu „…”' / 'the message “…” is not shown'."""
    if locator.text is not None:
        if lang == "pl":
            return f"nie widać komunikatu „{locator.text}”"
        return f"the message “{locator.text}” is not shown"
    if locator.role in ("dialog", "alertdialog", "status", "alert"):
        kind = "okna" if locator.role in ("dialog", "alertdialog") else "komunikatu"
        english = "window" if locator.role in ("dialog", "alertdialog") else "message"
        named = human_title(locator.name) if locator.name else None
        if lang == "pl":
            return f"nie widać {kind} „{named}”" if named else f"nie widać {kind}"
        return f"the “{named}” {english} is not shown" if named else f"no {english} is shown"
    noun = element_noun(locator, lang)
    name = locator.name or (getattr(locator, locator.strategy) if locator.role is None else "")
    if lang == "pl":
        whose = _NOT_SEEN.get(noun, noun)
        return f"nie widać {whose} „{name}”" if name else f"nie widać {whose}"
    return f"the “{name}” {noun} is not shown" if name else f"no {noun} is shown"


def element_appears(locator: Locator, lang: Lang) -> str:
    """'pojawia się pole „Price”' / 'the “Price” field appears'."""
    if locator.text is not None:
        return (
            f"{word(lang, 'message_appears')} „{locator.text}”"
            if lang == "pl"
            else (f"the message “{locator.text}” appears")
        )
    noun = element_noun(locator, lang)
    name = locator.name or (getattr(locator, locator.strategy) if locator.role is None else "")
    if lang == "pl":
        return f"pojawia się {noun} „{name}”" if name else f"pojawia się {noun}"
    return f"the “{name}” {noun} appears" if name else f"the {noun} appears"


def predicate_text(predicate: Predicate, model: ProcessModel, lang: Lang) -> str:
    if predicate.state is not None:
        name = state_name(model, predicate.state)
        return f"{word(lang, 'screen')} „{name}”" if lang == "pl" else f"the “{name}” screen"
    if predicate.visible is not None:
        target = predicate.visible
        if target.role == "status":
            return word(lang, "message_appears")
        if target.role in ("dialog", "alertdialog"):
            if not target.name:
                return word(lang, "dialog_appears")
            title = human_title(target.name)
            if lang == "pl":
                return f"{word(lang, 'dialog_appears')} „{title}”"
            return f"the “{title}” window appears"
        if target.role == "alert":
            return word(lang, "message_appears")
        return element_appears(target, lang)
    if (
        predicate.not_ is not None
        and predicate.not_.visible
        and predicate.not_.visible.role == "alert"
    ):
        return word(lang, "no_error")
    if predicate.hidden is not None:
        return element_absent(predicate.hidden, lang)
    if predicate.url is not None:
        return f"{word(lang, 'page_path')} {predicate.url}"
    if predicate.rows is not None:
        check = predicate.rows
        table = check.table[0].name or ("tabela" if lang == "pl" else "table")
        operator, count = next(
            (name, value)
            for name, value in (
                ("gt", check.count.gt),
                ("gte", check.count.gte),
                ("lt", check.count.lt),
                ("lte", check.count.lte),
                ("eq", check.count.eq),
            )
            if value is not None
        )
        return rows_phrase(table, dict(check.where), operator, count, lang)
    if predicate.field is not None:
        return field_text(predicate.field, lang)
    if predicate.value is not None:
        return value_text(predicate.value, model, lang)
    if predicate.not_ is not None:
        inner = predicate.not_
        if inner.field is not None and inner.field.equals is not None:
            return field_text(inner.field, lang).replace(" = ", " ≠ ", 1)
        if inner.value is not None and inner.value.equals is not None:
            return value_text(inner.value, model, lang).replace(" = ", " ≠ ", 1)
        said = predicate_text(inner, model, lang)
        return f"nie ({said})" if lang == "pl" else f"not ({said})"
    parts = [predicate_text(p, model, lang) for p in (predicate.all_ or predicate.any_ or [])]
    if predicate.any_:  # each way in brackets when it is made of more than one thing
        ways: list[str] = []
        for way, part in zip(predicate.any_, parts, strict=True):
            shown = f"({part})" if way.all_ else part
            if shown.casefold() not in {w.casefold() for w in ways}:  # one element, two ways found
                ways.append(shown)
        return " / ".join(ways) or "?"
    joiner = " i " if lang == "pl" else " and "
    return joiner.join(parts) or "?"


def field_text(check: FieldCheck, lang: Lang) -> str:
    """'„Status VAT” = Zwolniony': a field or a value shown under a label, by its name."""
    named = check.label or next(
        (n for loc in check.target or [] if (n := loc.column or loc.label or loc.name)), None
    )
    called = named or ("pole" if lang == "pl" else "field")
    quoted = f"„{called}”" if lang == "pl" else f"“{called}”"
    bounds = bounds_text(check)
    if bounds:
        return f"{quoted} {bounds}"
    if check.empty is not None:
        if lang == "pl":
            return f"{quoted} jest puste" if check.empty else f"{quoted} nie jest puste"
        return f"{quoted} is empty" if check.empty else f"{quoted} is not empty"
    if check.contains is not None:
        contains = "zawiera" if lang == "pl" else "contains"
        return f"{quoted} {contains} {check.contains}"
    return f"{quoted} = {check.equals}"


def bounds_text(check: FieldCheck | ValueCheck) -> str:
    """'≤ 7', '> 20000', 'od 1 do 7': the comparison of the number, in signs."""
    signs = [(check.gt, ">"), (check.gte, "≥"), (check.lt, "<"), (check.lte, "≤")]
    return " i ".join(f"{sign} {_number(bound)}" for bound, sign in signs if bound is not None)


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def value_text(check: ValueCheck, model: ProcessModel, lang: Lang) -> str:
    """'wartość „Faktura zbiorcza” = tak': the record's value as the sheet names it."""
    space, _, name = check.of.removeprefix("$").partition(".")
    spec = model.inputs.get(name) if space == "inputs" else None
    called = (spec.column or spec.description or name) if spec else name
    what = f"wartość „{called}”" if lang == "pl" else f"the value “{called}”"
    bounds = bounds_text(check)
    if bounds:
        return f"{what} {bounds}"
    if check.empty is not None:
        empty = check.empty
        if lang == "pl":
            return f"{what} {'jest pusta' if empty else 'nie jest pusta'}"
        return f"{what} is {'empty' if empty else 'not empty'}"
    if check.one_of is not None:
        joiner = " albo " if lang == "pl" else " or "
        return f"{what} = " + joiner.join(str(v) for v in check.one_of)
    return f"{what} = {check.equals}"


_INPUT_IN_TEXT = re.compile(r"\{inputs\.([a-z][a-z0-9_]*)\}")
"""A value of the record inside a question („Zapisać zmiany: Najem {inputs.numer}?”)."""


def window_texts(step: Step, model: ProcessModel, lang: Lang) -> list[str]:
    """Where the step is done and how the browser's own questions are answered ('W osobnym
    oknie „Wybór kontrahenta”', 'Przeglądarka pyta „Zapisać zmiany?”: OK')."""
    opening, closing = ("„", "”") if lang == "pl" else ("“", "”")

    def quoted(text: str) -> str:
        shown = _INPUT_IN_TEXT.sub(lambda match: "{" + match.group(1) + "}", text)
        return f"{opening}{shown}{closing}"

    texts = []
    last = bool(model.steps) and step.id == model.steps[-1].id  # no steps come after it
    if step.window:
        where = f" {quoted(state_name(model, step.in_state))}" if step.in_state else ""
        texts.append(word(lang, "in_window") + where)
    if step.opens_window:
        texts.append(word(lang, "opens_last" if last else "opens_window"))
    if step.closes_window:
        texts.append(word(lang, "closes_last" if last else "closes_window"))
    for dialog in step.dialogs:
        message = quoted(dialog.message or "")
        if dialog.kind == "alert":
            texts.append(word(lang, "shows_alert").format(message=message))
        elif dialog.kind == "prompt" and dialog.accept and dialog.value is not None:
            value = str(dialog.value).removeprefix("$inputs.")
            texts.append(word(lang, "asks_prompt").format(message=message, value=f"`{value}`"))
        else:
            answer = "OK" if dialog.accept else word(lang, "cancel")
            texts.append(word(lang, "asks_confirm").format(message=message, answer=answer))
    if any(d.kind != "alert" for d in step.dialogs):
        texts.append(word(lang, "other_question"))
    return texts


def step_value(step: Step) -> str | None:
    if isinstance(step.value, str) and step.value.startswith("$inputs."):
        return step.value.removeprefix("$inputs.")
    return None


def read_in(step: Step, model: ProcessModel) -> int | None:
    """The number of the step that read the value this step types (copied from a screen)."""
    if not (isinstance(step.value, str) and step.value.startswith("$vars.")):
        return None
    name = step.value.removeprefix("$vars.")
    return next((n for n, s in enumerate(model.steps, start=1) if s.save_as == name), None)


def step_rejections(step: Step, model: ProcessModel) -> list[tuple[str, str]]:
    """(exception id, description) raised by this step's outcomes."""
    found = []
    for handler in (step.on_outcome or {}).values():
        if handler.raise_ and handler.raise_ in model.exceptions:
            found.append((handler.raise_, model.exceptions[handler.raise_].description))
    return found


def rejection_lead(step: Step, exception_id: str, lang: Lang) -> str:
    """'Jeśli pojawi się komunikat' before a message; 'Jeśli widać' before a value the screen
    shows under a label („Status VAT”: Zwolniony), which is not a message."""
    for name, handler in (step.on_outcome or {}).items():
        shown = (step.outcomes or {}).get(name)
        if handler.raise_ != exception_id or shown is None:
            continue
        if shown.field is not None or (shown.not_ is not None and shown.not_.field is not None):
            return word(lang, "if_shown")
    return word(lang, "if_message")


def _good_outcomes(step: Step) -> dict[str, Predicate]:
    raised = {name for name, h in (step.on_outcome or {}).items() if h.raise_}
    return {name: p for name, p in (step.outcomes or {}).items() if name not in raised}


def documented(model: ProcessModel) -> ProcessModel:
    """The model as documents show it, without the robot's own check that the window a step
    clicks in is open while the person is already working in it (the step before was done on
    that screen and opened or closed no window): „pojawia się okno „Nowa wersja ceny”?” before
    „Zapisz” in that very window is no decision of the process. Nor is the window a Java
    program starts on (a navigator) before the first click in it: „the “Navigator” window
    appears?” right after „Open the program” was a branch no recording had. A window that
    comes after a step (a question after saving) keeps its condition."""
    steps = list(model.steps)
    changed = False
    java = model.application.kind == "java"
    for index, step in enumerate(steps):
        when = step.when
        if index == 0 or when is None or when.visible is None:
            continue
        if when.visible.role not in ("dialog", "alertdialog"):
            continue
        before = steps[index - 1]
        started = java and index == 1 and before.action is Action.NAVIGATE  # its first window
        if not started and (before.in_state is None or before.in_state != step.in_state):
            continue
        if not started and (before.opens_window or before.closes_window):
            continue
        steps[index] = step.model_copy(update={"when": None})
        changed = True
    return model.model_copy(update={"steps": steps}) if changed else model


def step_success(step: Step, model: ProcessModel, lang: Lang) -> str | None:
    """The usual result: ``expect``, else the ``done`` outcome (or the first good one)."""
    if step.expect is not None:
        return predicate_text(step.expect, model, lang)
    good = _good_outcomes(step)
    if good:
        return predicate_text(good.get("done", next(iter(good.values()))), model, lang)
    return None


def step_alternatives(step: Step, model: ProcessModel, lang: Lang) -> list[str]:
    """Other results that let the process go on (e.g. a confirmation dialog)."""
    good = _good_outcomes(step)
    usual = "done" if "done" in good else next(iter(good), None)
    return [predicate_text(p, model, lang) for name, p in good.items() if name != usual]


def choice_text(step: Step, model: ProcessModel, lang: Lang) -> str | None:
    """A decision the recordings made one way where another was offered („Akceptuj” in a row
    that also has „Korekta (CN)”): who makes it, or the rule the robot keeps to; None for a
    step that is no such decision."""
    if not step.alternatives or step.when is not None:  # under a rule: its condition says it
        return None
    chosen = next((t.name for t in step.target or [] if t.name), None) or step.intent
    mark = "„{}”" if lang == "pl" else "“{}”"
    others = ", ".join(mark.format(o) for o in step.alternatives)
    where = word(lang, "choice_row" if step.within is not None else "choice_screen")
    if step.executor is Executor.HUMAN:
        key = "choice_said" if step.note_when else "choice_person"
        return word(lang, key).format(chosen=chosen, where=where, others=others)
    if step.requires is not None:
        rule = predicate_text(step.requires, model, lang)
        return word(lang, "choice_rule").format(chosen=chosen, rule=rule, others=others)
    return word(lang, "choice_always").format(chosen=chosen, where=where, others=others)


def evidence_note(step: Step, lang: Lang) -> str | None:
    """'⚠ note' while a person has not confirmed it, '✓ note (potwierdzenie: Ania)' after."""
    evidence = step.evidence
    if evidence is None or not evidence.note:
        return None
    if evidence.confirmed_by:
        return f"✓ {evidence.note} ({word(lang, 'confirmed_by')}: {evidence.confirmed_by})"
    return f"⚠ {evidence.note}"
