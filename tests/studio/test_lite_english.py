"""Maptelo Lite's page in English: every word of the page's own that Lite shows has its English
(EN in app.js), and none is left outside t(), where English could not reach it."""

from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "src" / "maptelo" / "studio" / "static" / "app.js"
MARK = re.compile(r"^(\s*)// lite: (cut|else|end)\b ?(.*)$")
TOKEN = re.compile(
    r"""(?P<comment>/\*.*?\*/|//[^\n]*)
      | "(?P<double>(?:[^"\\\n]|\\.)*)"
      | '(?P<single>(?:[^'\\\n]|\\.)*)'
      | `(?P<template>(?:[^`\\]|\\.)*)`
      | (?<=[=(,:\[!&|?{};])\s*/(?![*/])(?:[^/\\\n\[]|\\.|\[(?:[^\]\\\n]|\\.)*\])+/[a-z]*""",
    re.S | re.X,
)
"""A JavaScript comment, string (three kinds) or regular expression, whichever starts first."""
WORD = re.compile(r"[A-Za-zÀ-ž]{3,}")
POLISH_LETTERS = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")


def lite_page() -> str:
    """app.js as Maptelo Lite has it: the full Maptelo's parts out, Lite's own lines in (its
    open copy has no marks left: then it is the file as it is)."""
    out: list[str] = []
    cutting, instead = False, []
    for line in APP.read_text(encoding="utf-8").splitlines():
        mark = MARK.match(line)
        if mark is None:
            if not cutting:
                out.append(line)
            continue
        indent, kind, rest = mark.groups()
        if kind == "cut":
            cutting, instead = True, []
        elif kind == "else":
            instead.append(indent + rest)
        else:
            out += instead
            cutting = False
    return "\n".join(out) + "\n"


def _block(page: str, name: str) -> re.Match[str]:
    found = re.search(rf"^const {name} = \{{.*?\}};\n", page, re.S | re.M)
    assert found is not None, name
    return found


def dictionary() -> tuple[dict[str, str], dict[str, str], str]:
    """EN, EN_PLURALS (each Polish word's English, one and many) and the rest of the page."""
    page = lite_page()
    words = _block(page, "EN")
    english = dict(re.findall(r'"((?:[^"\\]|\\.)*)":\s*"((?:[^"\\]|\\.)*)"', words.group(0)))
    rest = page[: words.start()] + page[words.end() :]
    plurals = _block(rest, "EN_PLURALS")
    counted = dict(re.findall(r'"?([^\s",:{}]+)"?:\s*\["[^"]+",\s*"([^"]+)"\]', plurals.group(0)))
    return english, counted, rest[: plurals.start()] + rest[plurals.end() :]


def test_every_word_given_to_t_has_its_english() -> None:
    english, _, rest = dictionary()
    asked = set(re.findall(r'\bt\("((?:[^"\\]|\\.)*)"', rest))
    assert asked, "the page says nothing through t()"
    assert sorted(asked - set(english)) == []


def test_every_english_keeps_the_places_of_what_is_put_in() -> None:
    english, _, _ = dictionary()
    assert [k for k, v in english.items() if k.count("{}") != v.count("{}")] == []


WORD_LISTS = [
    ("const CHECKS = {", "};"),
    ("const BROWSERS = [", "];"),
    ('[["processes", "Procesy"]', "]]"),
    ('["Data", "Uwagi"', "]"),
    ("const CARD_QUESTIONS = [", "];"),
]
"""Words the page gives to t() where it uses them: the names of the checks of this computer
and of the browsers, the side panel's links, the headings of a process's recordings, the
questions of the process card and their examples."""


def test_no_polish_word_of_the_page_is_left_where_english_cannot_reach() -> None:
    """A Polish sentence outside t() would stay Polish on the English page, even one EN knows.
    Polish-looking: Polish letters, or a word that EN translates (a word kept in the English
    too, like "Program" or "Proxy", is no sign)."""
    english, _, rest = dictionary()
    kept = {w.lower() for value in english.values() for w in WORD.findall(value)}
    polish_words = {
        w.lower() for key in english for w in WORD.findall(key) if w.lower() not in kept
    }
    counts = {
        s for call in re.findall(r"plural\(([^)]*)\)", rest) for s in re.findall(r'"([^"]*)"', call)
    }
    lists = []
    for start, end in WORD_LISTS:
        at = rest.index(start)
        lists.append(range(at, rest.index(end, at) + len(end)))
    left = []
    for match in TOKEN.finditer(rest):
        text = next(
            (match[k] for k in ("double", "single", "template") if match[k] is not None), None
        )
        if text is None or text in counts:
            continue
        given = rest[max(0, match.start() - 2) : match.start()] == "t("
        listed = any(match.start() in span for span in lists)
        said = {w.lower() for w in WORD.findall(re.sub(r"\$\{[^}]*\}", " ", text))}
        if (POLISH_LETTERS.search(text) or said & polish_words) and not (given or listed):
            left.append(text)
    assert left == [], "give these to t() (and EN)"
    assert counts  # the counted words are checked below


def test_every_counted_word_has_its_english() -> None:
    _, counted, rest = dictionary()
    first = set(re.findall(r'plural\([^,]+,\s*"([^"]+)"', rest))
    assert first
    assert sorted(first - set(counted)) == []
