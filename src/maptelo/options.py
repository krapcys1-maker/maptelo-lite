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
