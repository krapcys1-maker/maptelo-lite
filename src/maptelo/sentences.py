"""Values read from sentences: the word after given words, in what a screen says.

People copy values out of running text too: the claim number the carrier's page gives in its
message („Zgłoszono szkodę SZK/2026/0001.”), the delivery date in an e-mail („Termin dostawy:
2026-10-20”). Such a value has no place named in words (a term, a field, a column); the
words it follows name it instead (benchmark p11, p20). The mapping finds those words, the
runtime and the exported script read the value after them again.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# The exported script carries this module from here on (export/playwright_py.py).

ENDS = ".,;:!?)]}\"'\u201d\u2019\u00bb"
"""What may close a value in a sentence and is not part of it („SZK/2026/0001.”)."""
LEAD_WORDS = 3
"""At most this many words before a value name it."""


def _whole_word(value: str) -> re.Pattern[str]:
    """A value as a whole word of a text."""
    return re.compile(r"(?<!\S)" + re.escape(value) + r"(?=[\s" + re.escape(ENDS) + r"]|$)")


def lead_before(text: str, value: str) -> str | None:
    """The words ``value`` follows in ``text``, when it stands there once: the label before it
    („Termin dostawy:”) or the words of the message („Zgłoszono szkodę”). Back from the value
    to the end of the part before it (a word that ends with . , ; ) or holds a number, which
    differ from record to record), at most ``LEAD_WORDS`` words; None when there are none."""
    found = list(_whole_word(value).finditer(text))
    if len(found) != 1:
        return None
    words = text[: found[0].start()].split()
    lead: list[str] = []
    for word in reversed(words):
        if len(lead) == LEAD_WORDS or any(ch.isdigit() for ch in word):
            break
        if lead and word[-1] in ".,;)]":
            break
        if not lead and word[-1] in ".;)]":
            break  # the value starts a part of its own
        lead.insert(0, word)
    return " ".join(lead) or None


def lead_of_rest(text: str, value: str) -> str | None:
    """The label a message starts with when ``value`` is the whole rest of it: „Kontrole: Kwota
    poza tolerancją: …” gives „Kontrole” for „Kwota poza tolerancją: …”. A few words and a
    colon, no number among them (it differs from record to record); None otherwise."""
    text, value = " ".join(text.split()), " ".join(value.split())
    if not value or text == value or not text.endswith(value):
        return None
    head = text[: len(text) - len(value)].strip()
    if not head.endswith(":"):
        return None
    words = head.rstrip(":").split()
    if not words or len(words) > LEAD_WORDS or any(ch.isdigit() for ch in head):
        return None
    if not any(ch.isalpha() for ch in head):
        return None  # a mark („✘”), not words
    return " ".join(words)


def rest_after(texts: Iterable[str], lead: str) -> set[str]:
    """The rest of each line that starts with ``lead`` and a colon, in these texts (a page and
    its frames): a message a person copies whole after its label („Kontrole: Kwota poza
    tolerancją: zamówienie x przyjęcie = 8 520,00 zł”)."""
    words = r"\s+".join(re.escape(word) for word in lead.split())
    pattern = re.compile(r"^\W*" + words + r"\s*:\s*(\S.*)$")
    found = set()
    for text in texts:
        for line in text.splitlines():
            match = pattern.match(line.strip())
            if match:
                found.add(" ".join(match.group(1).split()))
    return found


def shape(value: str) -> str:
    """What a value looks like, loosely: letters A, digits 9, the rest as it is („PO-10001” is
    A-9, „2026-10-20” 9-9-9, „25” 9)."""
    return re.sub(r"\d+", "9", re.sub(r"[^\W\d_]+", "A", value))


def words_after(texts: Iterable[str], lead: str, like: str | None = None) -> set[str]:
    """The values that follow ``lead`` in these texts (a page and its frames): one word each,
    without what closes a sentence after it; ``like``: only those shaped so (``shape``), as
    the same words may come before another word („zamówienia nr telefonu”)."""
    words = r"\s+".join(re.escape(word) for word in lead.split())
    pattern = re.compile(r"(?<!\w)" + words + r"\s*:?\s*(\S+)")
    found = set()
    for text in texts:
        for match in pattern.finditer(text):
            value = match.group(1).rstrip(ENDS)
            if value and (like is None or shape(value) == like):
                found.add(value)
    return found
