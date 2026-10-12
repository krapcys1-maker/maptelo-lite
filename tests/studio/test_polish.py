"""Studio in Polish: what the core says reaches the page translated, with what it names kept
as it is; and every sentence the core can say has its Polish, or is known not to reach the
page."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from maptelo.studio.polish import polish

CORE = Path(__file__).resolve().parents[2] / "src" / "maptelo"
SCANNED = ["runtime", "data", "studio", "repair"]
# doctor, environment: both languages
SCANNED_FILES = [
    "policy.py",
    "calendars.py",
    "desktop/jab.py",
    "browser.py",
]

NOT_FOR_THE_PAGE = {
    # questions and feedback for the AI agent (it reads English), never shown as a message
    "recognise the screen “{}”", "check which screen is shown", "its landmarks are shown: {}",
    "find the table that “{}” picks a row from", "pick a row", "what shows that this is the "
    "screen “{}”, which used to be at the address {}; the browser is now at {}. Answer "
    "found=false if another screen is shown", "inside the row of the table “{}” where {}",
    "the screen “{}” is shown", "a message like “{}” appears (its wording may be different now)",
    "a {}{} appears (its name may be different now, but it is still a {})", "needs the {}",
    "an element without a name", "the element must have the role \"{}\"",
    "it must be a {}, like the element it replaces", "it must be a message text, like the old one",
    "scripted: not on the screen", "state {}, {}", "step {} (result {})", "no result named",
    "a condition: {}",
    # a CSS selector the robot uses (the check box in a list's cell), never shown
    "input[type=checkbox], input[type=radio], [role=checkbox], [role=radio], [role=switch]",
    # what the model that reads a document's picture is told about a field
    "the 10-digit tax number", "an amount of money", "a bank account number",
    "scripted document reader",  # the name of the reader tests use
    # descriptions in files and on the command line (shadow.md, the CLI), not on the page
    "the robot would have done the same", "the robot would have done something else",
    "people have not done it yet (or did something else that left nothing)",
    "the robot could not go through it: see why", "it was done before the robot looked",
    "the record's values are not valid for this process", "the robot has not gone through it yet",
    "robot could not", "ready | would refuse | could not | already done | rejected | not rehearsed",
    "done | not done | done differently | cannot tell", "running | done | stopped | failed",
    "job %s failed", "{}, sheet {}", "{} at {}", "a model on this computer: the screen does not "
    "leave it",
    # what the MCP catalog tells the agent, and the command a host runs
    "independent read {}: {} ({})", "the sheet “{}”", "{}: {}: {}",
    "claude mcp add {} -e PYTHONIOENCODING=utf-8 -- {}",
    # what Studio says in its console when it starts and stops (the command line's language)
    "no Edge or Chrome for a window here: the page opens in the default browser",
    "the window did not show up; Ctrl+C stops Studio", "the window was closed: Studio stops",
    "removed {} evidence files older than {} days (policy)",
    # code and checks, not sentences
    "intent => { window.__mapteloPointIntent = intent; }", "no unique visible element",
    "its button has new words",
    "translate(@type, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')",
    "{}//button[not(@type) or string-length(@type) = 0 or {} = 'submit']",
    "{}//input[{} = 'submit' or {} = 'image']",
    "normalize-space(.)={} or normalize-space(.)=concat({}, ':')",
    # names and parts of names, not sentences
    "{} = {}", "{} → {}", "column {} → {}", "screen {}: {} → {}", "toolbar button #",
    # already Polish
    "{}: tryb cienia, {} wierszy",
    # parts of sentences Maptelo Lite says in place of others (app.py, LITE_WORDS)
    "can be recorded and run", "can be recorded",
}  # fmt: skip


def _shape(node: ast.AST) -> str | None:
    """A string, an f-string or "text" + something, as a shape: what it puts in is {}."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            str(part.value) if isinstance(part, ast.Constant) else "{}" for part in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _shape(node.left), _shape(node.right)
        if left is not None or right is not None:
            return (left if left is not None else "{}") + (right if right is not None else "{}")
    return None


def sentences_of_the_core() -> set[str]:
    found = set()
    paths = [p for folder in SCANNED for p in sorted((CORE / folder).glob("*.py"))]
    for path in [*paths, *(CORE / name for name in SCANNED_FILES)]:
        if path.name == "polish.py":
            continue  # the translations themselves
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
                skip.add(id(body[0].value))  # docstrings
            if isinstance(node, ast.JoinedStr):
                skip.update(id(part) for part in node.values)  # parts of an f-string
            if isinstance(node, ast.BinOp) and _shape(node) is not None:
                skip.update((id(node.left), id(node.right)))  # parts of "text" + something
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "say":
                skip.update(id(arg) for arg in node.args[1:])  # written in both languages
        for node in ast.walk(tree):
            shape = _shape(node)
            if id(node) in skip or shape is None or len(shape.split()) < 3:
                continue
            if shape[0].islower() or shape[0] in "“'{" or shape.startswith(("AI ", "IT's ")):
                found.add(shape)
    return {s for s in found if not s.startswith(("{} | ", "| ")) and "\n" not in s}


def _example(shape: str) -> str:
    """The shape with made-up names in its slots."""
    names = iter(f"X{n}" for n in range(1, 20))
    return re.sub(r"\{\}", lambda _: next(names), shape)


def test_every_sentence_of_the_core_has_its_polish() -> None:
    untranslated = sorted(
        shape
        for shape in sentences_of_the_core() - NOT_FOR_THE_PAGE
        if polish(_example(shape)) == _example(shape)
        and not re.search(r"[ąćęłńóśźż„]", shape)  # Polish already
        and not shape.startswith(("td[", "xpath=", "el =>", "els =>", "default-src", "sandbox "))
    )
    assert untranslated == [], "add these to studio/polish.py (or to NOT_FOR_THE_PAGE)"


@pytest.mark.parametrize(
    ("english", "polish_text"),
    [
        ("dry run: stopped before “Zapisz zmianę ceny”",
         "próba bez zapisu: zatrzymany przed „Zapisz zmianę ceny”"),
        ("effect 'price_set' not confirmed: price: expected 135.00, found 136.00",
         "efekt „price_set” niepotwierdzony: price: oczekiwano 135.00, jest 136.00"),
        ("price: expected 135.00, found 136.00; valid_from: expected 2026-12-01, found "
         "2026-11-01",
         "price: oczekiwano 135.00, jest 136.00; valid_from: oczekiwano 2026-12-01, jest "
         "2026-11-01"),
        ("Wybierz Product: wpisz i wybierz: no suggestion contains “99999-Z”",
         "Wybierz Product: wpisz i wybierz: żadna podpowiedź nie zawiera „99999-Z”"),
        ("input 'new_price': expected a number, got 'abc'; input 'cpn' is required",
         "dana „new_price”: oczekiwano liczby, jest 'abc'; dana „cpn” jest wymagana"),
        ("cannot check whether this was already done (cannot read the system of record: timed "
         "out); nothing was written",
         "nie da się sprawdzić, czy to już zrobione (nie da się odczytać systemu: timed out); "
         "nic nie zapisano"),
        ("Kliknij „Save”: stopped on request; run again to do the rest",
         "Kliknij „Save”: zatrzymano na prośbę; uruchom ponownie, żeby zrobić resztę"),
        ("ceny.csv: no column 'CPN' (input cpn); the column 'Cena' is there 2 times "
         "(columns: Klient, Cena, Cena)",
         "ceny.csv: brak kolumny „CPN” (dana cpn); kolumna „Cena” występuje 2 razy "
         "(kolumny: Klient, Cena, Cena)"),
    ],
)  # fmt: skip
def test_sentences_in_sentences(english: str, polish_text: str) -> None:
    assert polish(english) == polish_text
    assert polish(polish_text) == polish_text  # Polish stays as it is


@pytest.mark.parametrize(
    "data",
    [
        "Klient nie ma produktu o podanym CPN",  # the model's own words
        "No product found for CPN 99999-Z.",  # what the application said on the screen
        "HTTP 502",
        "",
    ],
)
def test_what_the_application_and_the_model_say_is_left_alone(data: str) -> None:
    assert polish(data) == data
