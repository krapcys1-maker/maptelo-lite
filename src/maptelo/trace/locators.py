"""Locator ladders: several independent ways to find the same element again."""

from __future__ import annotations

import json
from typing import Any

from maptelo.model.schema import Locator
from maptelo.trace.schema import ElementInfo

# Roles whose accessible name is too vague to identify an element on its own.
_WEAK_ROLES = {"generic", "none", "presentation", "group", "rowgroup", "cell", "row"}
_TEXT_ROLES = {"button", "link", "menuitem", "tab", "option"}


def candidates_for(element: ElementInfo) -> list[Locator]:
    """Most robust first: accessibility (role + name), label, the form field's name, test id,
    what a button does (its name), the form a button sends, placeholder, an icon's tooltip, its
    own classes, text, CSS."""
    found: list[Locator] = []

    def add(**strategy: Any) -> None:
        locator = Locator(**strategy)
        if locator not in found:
            found.append(locator)

    if element.role and element.name and element.role not in _WEAK_ROLES:
        add(role=element.role, name=element.name)
    elif element.role and element.column and element.role not in _WEAK_ROLES:
        add(role=element.role, column=element.column)  # an unlabeled input in a grid
    if element.label:
        add(label=element.label)
    if element.field:
        add(field=element.field)
    if element.testid:
        add(testid=element.testid)
    if element.action:
        add(action=element.action)
    if element.submits:
        add(submits=element.submits)
    if element.placeholder:
        add(placeholder=element.placeholder)
    if element.title and not (element.role and element.name):  # an icon named by its tooltip
        add(css=f"[title={json.dumps(element.title, ensure_ascii=False)}]")
    if element.classes:
        add(css=element.classes)
    if element.text and (element.tag in ("a", "button") or element.role in _TEXT_ROLES):
        add(text=element.text)
    if element.css:
        add(css=element.css)
    return found
