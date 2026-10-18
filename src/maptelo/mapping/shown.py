"""Where a value the person typed had been shown: a place on a screen a robot can read again.

People copy values from one screen into another: the account number from the VAT white list,
the rate from the bank's table, the parcel number from the courier's page. Such a value is not
a column of the sheet the person worked from: a robot reads it from that screen (a ``read``
step) and types what it read (benchmark: copied_value_as_input).

Only a place named in words counts: the definition of a term (``Numer rachunku``: PL61...),
a cell under a column header, a field with a name, or the words a value follows in a
sentence („Zgłoszono szkodę SZK/2026/0001.”, an e-mail's „Termin dostawy: 2026-10-20”;
``maptelo.sentences``). A short or common value ("4", "Tak") is shown in many places by
chance, so it is taken for a copy only right after the field's own name („Ilość: 25”).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from maptelo.sentences import lead_before, lead_of_rest, rest_after, shape, words_after
from maptelo.trace.aria import AriaNode, parse_aria, table_row_nodes

_FIELDS = ("textbox", "searchbox", "spinbutton")
_SPACES = re.compile(r"\s+")

Kind = Literal["term", "field", "cell", "words"]
_PREFERRED: tuple[Kind, ...] = ("term", "field", "cell", "words")
"""A term says best what a value is; a cell needs its row found too; words in a sentence
come last."""
_SAYS = ("paragraph", "text", "status", "alert", "note", "listitem", "blockquote", "strong",
         "emphasis", "generic", "cell", "heading", "caption", "region", "article",
         "document")  # fmt: skip
"""What says something in sentences."""


@dataclass(frozen=True)
class Place:
    kind: Kind
    label: str
    """The term, the field's name or the column header the value stood under."""
    role: str = ""
    """For a field: its role (textbox, spinbutton...)."""
    table: str | None = None
    row: tuple[tuple[str, str], ...] = ()
    """For a cell: the cells of its row (column header, text)."""
    rows: tuple[tuple[tuple[str, str], ...], ...] = ()
    """For a cell: every data row of its table."""
    lead: str = ""
    """For words: what the value follows in its sentence („Termin dostawy:”)."""
    rest: bool = False
    """For words: the value is the whole rest of a message after its label, not one word."""


TRADE_MARKS = re.compile("[" + "".join(map(chr, (0xAE, 0x2122, 0xA9, 0x2120))) + "]")
"""Registered, trade, copyright and service marks: a shop writes „Gobi HeatTec® Tee” where the
sheet says „Gobi HeatTec Tee” (WebArena-Verified), the same product."""


CLOSE_MARKS = frozenset({"x", *map(chr, (0xD7, 0x2715, 0x2716, 0x2573, 0x2A2F))})
"""How a window's close button is drawn: a cross (x, the multiplication sign, ✕, ✖ …). Its
name is „Close” („Zamknij”)."""
CLOSE_NAMES = re.compile(r"^\W*(close|zamknij|schließen|fermer|cerrar|chiudi)\W*$", re.IGNORECASE)
"""The names pages give a window's close button."""


MARKS_MAY = "[" + "".join(map(chr, (0xAE, 0x2122, 0xA9, 0x2120))) + "]?"
"""A word of a name may carry a registered or trade mark on screen that the sheet leaves out."""
ANY_WORD = "{*}"
"""In a name: one word that changes from record to record („Przyjęto: {*}” for the field of
the item „Przyjęto: 37241-E”)."""


def plain(text: str) -> str:
    return _SPACES.sub(" ", TRADE_MARKS.sub("", text)).strip()


def distinctive(value: str) -> bool:
    """A value unlikely to stand anywhere by chance: a number with four digits or more, or
    words long enough to be a name (not "4", "Tak", "Czynny")."""
    text = plain(value)
    digits = sum(ch.isdigit() for ch in text)
    return digits >= 4 or len(text) >= 8 or (" " in text and len(text) >= 5)


def measure(value: str) -> bool:
    """An amount or a date (129,90; 1 234.50 zł; 2027-01-15; 15.01.2027): a value a record has,
    which another record may have as well, never the name of one."""
    text = (
        plain(value).replace(" ", "").replace(chr(0xA0), "").removesuffix("zł").removesuffix("PLN")
    )
    if re.fullmatch(r"-?\d+[.,]\d{1,2}|-?\d{1,3}([.,]\d{3})+[.,]\d{2}", text):
        return True
    return re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{4}", text) is not None


def names_one(value: str) -> bool:
    """A value that can name one record in an address: a code with letters and digits
    (C001, ZS/2026/0002) or a number of four digits or more. "2" may be a quantity as well as
    an order, so an address with it is not taken from the data by chance."""
    text = plain(value)
    letters, digits = any(ch.isalpha() for ch in text), any(ch.isdigit() for ch in text)
    return distinctive(text) or (letters and digits and len(text) >= 3)


def places(aria: str, value: str) -> list[Place]:
    """Where on this screen ``value`` stands, in places with words of their own."""
    wanted = plain(value)
    if not wanted:
        return []
    root = parse_aria(aria)
    found = list(_terms_and_fields(root, wanted))
    for table in (n for n in root.walk() if n.role in ("table", "grid")):
        rows = [tuple(values.items()) for _, values in table_row_nodes(table)]
        for row in rows:
            for header, text in row:
                if plain(text) == wanted and not header.startswith("#"):
                    found.append(Place("cell", header, "cell", table.name, row, tuple(rows)))
    if " " not in wanted:  # last: what a value in a sentence follows
        found += _in_sentences(root, wanted)
    else:  # a message copied whole after its label (the failed check as a reason)
        found += _rest_of_messages(root, wanted)
    return found


def _rest_of_messages(root: AriaNode, wanted: str) -> list[Place]:
    """The value as the rest of a message after its label, on this screen once: the same label
    before another message leaves it unknown which one is meant."""
    texts = [plain(node.value) for node in root.walk() if node.role in _SAYS and node.value]
    leads = {lead for text in texts if (lead := lead_of_rest(text, wanted)) is not None}
    return [
        Place("words", lead, lead=lead, rest=True)
        for lead in sorted(leads)
        if rest_after(texts, lead) == {wanted}
    ]


def _in_sentences(root: AriaNode, wanted: str) -> list[Place]:
    """The value as a word of a sentence, after words that name it on this screen alone: the
    same words followed by another value elsewhere leave it unknown which one is meant."""
    texts = [plain(node.value) for node in root.walk() if node.role in _SAYS and node.value]
    leads = {lead for text in texts if (lead := lead_before(text, wanted)) is not None}
    return [
        Place("words", lead.rstrip(":").strip() or lead, lead=lead)
        for lead in sorted(leads)
        if words_after(texts, lead) == {wanted}
    ]


def alone_on_screen(aria: str, found: list[Place], value: str) -> list[Place]:
    """The places with words whose words, anywhere on the screen (a list beside the e-mail
    included, as a run reads it), are followed by this value only."""
    root = parse_aria(aria)
    texts = [plain(f"{node.name or ''} {node.value or ''}") for node in root.walk()]
    texts = [text for text in texts if text]
    like = shape(plain(value))
    return [
        place
        for place in found
        if place.kind == "words"
        and (
            rest_after(texts, place.lead) == {plain(value)}
            if place.rest
            else words_after(texts, place.lead, like) == {plain(value)}
        )
    ]


def best(found: list[Place]) -> Place | None:
    """The one place a value is read from: of the kind that says most, and only one such
    (two terms showing the same value leave it unknown which one the person read)."""
    for kind in _PREFERRED:
        of_kind = {p for p in found if p.kind == kind}
        if len(of_kind) == 1:
            return next(iter(of_kind))
        if of_kind:
            return None
    return None


def _terms_and_fields(root: AriaNode, wanted: str) -> Iterator[Place]:
    for node in root.walk():
        term: str | None = None
        for child in node.children:
            if child.role == "term":
                term = plain(child.text())
            elif child.role == "definition" and term and plain(child.text()) == wanted:
                yield Place("term", term)
            if child.role in _FIELDS and child.name and _field_value(child) == wanted:
                yield Place("field", child.name, child.role)


def _field_value(node: AriaNode) -> str | None:
    """What a field shows: its value, or the text inside it (not its placeholder)."""
    if node.value:
        return plain(node.value)
    texts = [c.value for c in node.children if c.role == "text" and c.value]
    return plain(" ".join(texts)) if texts else None
