"""An option of a list chosen by the words of a text (benchmark p11): the customer of an order
e-mail is picked from the ERP's list of customers by the words the e-mail names it with
(„Dział zakupów, Sklep internetowy Grądziel-Lew” names „Sklep internetowy Grądziel-Lew
(K0013)”). An option counts when every word of its name stands in the text; of those, the one
with most words is chosen, and only when no other has as many: two customers named alike are
not guessed between.
"""

from __future__ import annotations

import re

# The exported script carries this module from here on (export/playwright_py.py).

_WORD = re.compile(r"[^\W_]+(?:[-'" + chr(0x2019) + r"][^\W_]+)*")
_CODE = re.compile(r"\s*[(\[][^)\]]*[)\]]\s*")


def option_name(label: str) -> str:
    """An option's name without the code beside it: „Sklep internetowy Grądziel-Lew (K0013)”
    is „Sklep internetowy Grądziel-Lew”."""
    return " ".join(_CODE.sub(" ", label).split())


def words_of(text: str) -> set[str]:
    """The words of a text that can name something: three letters or more, or with a digit
    (not „sp.”, „z”, „o.o.”)."""
    return {
        word
        for word in _WORD.findall(text.casefold())
        if len(word) >= 3 or any(ch.isdigit() for ch in word)
    }


def named_in(options: list[tuple[str, str]], text: str) -> str | None:
    """The value of the one option ``text`` names: every word of its name stands in the text,
    and no other option with as many words does. ``options``: (label, value)."""
    said = words_of(text)
    named: list[tuple[int, str]] = []
    for label, value in options:
        words = words_of(option_name(label))
        if words and words <= said:
            named.append((len(words), value))
    if not named:
        return None
    most = max(count for count, _ in named)
    best = {value for count, value in named if count == most}
    return next(iter(best)) if len(best) == 1 else None


def option_named_by(options: list[tuple[str, str]], value: str) -> str | None:
    """The code of the one option a record's value names, when no option's code or label is
    the value as written: an option whose label is it in other letters („On Hold” for „on
    hold”: the list matches labels letter for letter), else one whose label starts with it as
    a code („C002 · Globex Retail S.A.” for C002), else one whose code is it in other letters
    („UPS” for ``ups``), else one whose label's words begin with its letters („USPS”: United
    States Postal Service; WebArena-Verified, a carrier from the task's words). Two that fit:
    none (no guessing)."""

    def norm(text: str) -> str:
        return " ".join(text.split()).casefold()

    wanted = norm(value)
    if not wanted:
        return None
    written = " ".join(value.split())
    if any(code == value or " ".join(label.split()) == written for label, code in options):
        return None  # as written: the list finds it itself
    listed = [(norm(label), code) for label, code in options]
    for fits in (
        lambda label, code: label == wanted,
        lambda label, code: label.startswith(wanted + " "),
        lambda label, code: code.casefold() == wanted,
        # a short form written as one: capitals only („UPS”), never a word that happens to fit
        lambda label, code: (
            value.strip().isupper() and value.strip().isalpha() and _initials(label) == wanted
        ),
    ):
        found = [code for label, code in listed if fits(label, code)]
        if len(found) == 1:
            return found[0]
        if found:
            return None
    return None


def _initials(label: str) -> str | None:
    """The first letters of a label's words (united parcel service: ups), for a value of two
    letters or more written as such a short form."""
    words = re.findall(r"[^\W\d_]+", label)
    return "".join(w[0] for w in words) if len(words) >= 2 else None
