"""Studio in Polish: what the core says reaches the page translated, with what it names kept
as it is; and every sentence the core can say has its Polish, or is known not to reach the
page."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from maptelo.studio.polish import SENTENCES, polish

CORE = Path(__file__).resolve().parents[2] / "src" / "maptelo"
SCANNED = ["runtime", "data", "studio", "repair"]
# doctor, environment: both languages
SCANNED_FILES = [
    "policy.py",
    "formats.py",
    "calendars.py",
    "desktop/jab.py",
    "desktop/jab_remote.py",
    "browser.py",
]

NOT_FOR_THE_PAGE = {
    # the line the Java Access Bridge's helper Python runs (desktop/jab_remote.py)
    "import sys; sys.path.insert(next((n for n, p in enumerate(sys.path) if 'site-packages' in p), "
    "len(sys.path)), sys.argv[1]); from maptelo.desktop.jab_remote import serve; serve()",
    # a Java Access Bridge role the recorder compares with (desktop/jab.py), never shown
    "check box menu item",
    # the start of a failed read's detail, compared with (runtime/verify.py), never shown alone
    "cannot read the system of record",
    # a job's states, its line in the log and a sheet's name (studio/jobs.py, data/tables.py)
    "running | done | stopped | failed", "job %s failed", "{}, sheet {}",
    # what Studio says in its console when it starts and stops (the command line's language)
    "no Edge or Chrome for a window here: the page opens in the default browser",
    "the window did not show up: the page opens in the default browser",
    "the window was closed: Studio stops", "{} is already running: {}",
    "removed {} evidence files older than {} days (policy)",
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


def test_no_rule_is_left_without_a_sentence() -> None:
    """A rule whose sentence the core no longer says is dead: keep the list honest (Maptelo
    Lite's list holds only the sentences Lite says)."""
    shapes = {re.sub(r"\{\w+\}", "{}", english) for english, _ in SENTENCES}
    said = sentences_of_the_core()
    short = {s for s in shapes if len(s.split()) < 3}  # too short for the scan to find
    model_values = {  # said by the model's schema when an input is coerced (model/schema.py)
        "{} is below the minimum {}", "{} is above the maximum {}", "expected text, got {}",
        "{} does not match the pattern {}", "{} is not one of: {}",
        "expected an integer, got {}", "expected a number, got {}",
        "expected a finite number, got {}", "expected a date as YYYY-MM-DD, got {}",
        "expected true/false, got {}",
    }  # fmt: skip
    library = {  # said by Python's urllib when the read address cannot be reached
        "<urlopen error {}>", "[Errno {}] getaddrinfo failed",
        "[WinError {}] No connection could be made because the target machine actively "
        "refused it",
    }  # fmt: skip
    assert sorted(shapes - said - short - model_values - library) == []


@pytest.mark.parametrize(
    ("english", "polish_text"),
    [
        ("IT's policy C:\\ProgramData\\Maptelo\\policy.yaml is not valid: browser.channel: Input "
         "should be 'chromium', 'msedge' or 'chrome'",
         "zasady IT C:\\ProgramData\\Maptelo\\policy.yaml są niepoprawne: browser.channel: Input "
         "should be 'chromium', 'msedge' or 'chrome'"),
        ("the Java Access Bridge did not start (the Java Access Bridge could not start: "
         "[WinError 126] The specified module could not be found)",
         "Java Access Bridge nie wystartował (Java Access Bridge nie mógł wystartować: "
         "[WinError 126] The specified module could not be found)"),
        ("20261018T101512000000Z is still in use (Windows says 32); close its preview or the "
         "program using its files and try again",
         "Pliki nagrania 20261018T101512000000Z są nadal używane (kod Windows: 32). Zamknij ich "
         "podgląd lub program, który je otworzył, i spróbuj ponownie."),
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
