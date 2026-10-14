"""Decisions a screen offers: one command grants what was asked for (accepts an invoice, a
claim), others refuse it or send it back (a correction, a dispute, a hold). A recording that
chose one of them shows the choice, never when another is made."""

from __future__ import annotations

import re
from typing import Literal

from maptelo.trace.aria import AriaNode, table_row_nodes
from maptelo.trace.schema import ElementInfo

GRANTS = re.compile(
    r"^(przyjmij|przyjęcie|(za)?akceptuj|zatwierd[zź]|uznaj|approve|accept\b|grant\b)",
    re.IGNORECASE,
)
REFUSES = re.compile(
    r"^(odrzu[cć]|odmów|odmow|nie uznaj|reject|decline|deny|refuse)", re.IGNORECASE
)
DISPUTES = re.compile(
    r"^(korekt|koryguj|skoryguj|reklamuj|wstrzymaj|odeślij|odeslij|do wyja[śs]nienia|sporn|"
    r"zg[łl]o[śs] (rozbie[żz]no|b[łl][ąa]d)|eskaluj|"
    r"dispute|request (a )?correction|credit note|put on hold|hold\b|escalate)",
    re.IGNORECASE,
)
"""Sending it back instead of granting it: a correction of the document („Korekta (CN)”,
benchmark M6), a complaint, a hold, a dispute."""

Kind = Literal["grant", "refuse", "dispute"]


def decision_kind(words: str) -> Kind | None:
    """What a command decides, by its words; None for a command that decides nothing."""
    words = words.strip()
    if GRANTS.match(words):
        return "grant"
    if REFUSES.match(words):
        return "refuse"
    if DISPUTES.match(words):
        return "dispute"
    return None


def _plain(text: str) -> str:
    return " ".join(text.split()).casefold()


def row_node(screen: AriaNode, target: ElementInfo) -> AriaNode | None:
    """The table row the element was in, on the screen read before the click: by the cells the
    recorder saw (those under a header), else by its place among the rows."""
    if target.row is None:
        return None
    table = screen.find("table", target.row.table or None)
    if table is None:
        return None
    rows = table_row_nodes(table)
    wanted = {
        column: _plain(value)
        for column, value in target.row.cells.items()
        if value and value.strip() and not column.startswith("#")
    }
    if wanted:
        for node, values in rows:
            if all(_plain(values.get(column, "")) == value for column, value in wanted.items()):
                return node
        return None
    index = target.row.index
    return rows[index][0] if index is not None and 0 <= index < len(rows) else None


def offered_choices(screen: AriaNode | None, target: ElementInfo, chosen: str) -> list[str]:
    """The other decisions offered where ``chosen`` was clicked: for a command in a table's
    row, the row's other buttons and links („Korekta (CN)” beside „Akceptuj”, benchmark M6);
    else the screen's other buttons („Odrzuć reklamację” beside „Przyjmij reklamację”, p18).
    A grant's others refuse it or send it back; a refusal's or a correction's others grant it."""
    kind = decision_kind(chosen)
    if screen is None or kind is None:
        return []
    if target.row is not None:
        place = row_node(screen, target)
        found = (
            [n for n in place.walk() if n.role in ("button", "link")] if place is not None else []
        )
    else:
        found = screen.find_all("button")
    others = []
    for node in found:
        words = (node.name or "").strip()
        other = decision_kind(words) if words and words != chosen.strip() else None
        if other is not None and (other == "grant") != (kind == "grant"):
            others.append(words)
    return list(dict.fromkeys(others))
