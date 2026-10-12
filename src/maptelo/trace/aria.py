"""Reading Playwright accessibility snapshots (the ``aria`` text stored in trace states).

A snapshot is an indented list: ``- role "name" [attr]: value`` with children below.
This parser turns it into a tree, so mapping can look at tables, messages and fields.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

_LINE = re.compile(
    r'^(?P<indent>\s*)- (?P<role>[^\s":\[]+)'
    r'(?: "(?P<name>(?:[^"\\]|\\.)*)")?'
    r"(?P<attrs>(?: \[[^\]]*\])*)"
    r"(?::(?: (?P<value>.*))?)?$"
)
_ATTR = re.compile(r"\[([^\]=]+)(?:=([^\]]*))?\]")
_QUOTED_KEY = re.compile(r"^(?P<indent>\s*)- '(?P<key>(?:[^']|'')*)'(?P<rest>(?::.*)?)$")
"""A line whose role and name YAML had to quote: a name with „: ” in it
(``- 'button "Wybierz: Kontrahent"': …``)."""


def _plain_line(line: str) -> str:
    quoted = _QUOTED_KEY.match(line)
    if quoted is None:
        return line
    key = quoted.group("key").replace("''", "'")
    return f"{quoted.group('indent')}- {key}{quoted.group('rest')}"


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return text


@dataclass
class AriaNode:
    role: str
    name: str | None = None
    value: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[AriaNode] = field(default_factory=list)

    def walk(self) -> Iterator[AriaNode]:
        yield self
        for child in self.children:
            yield from child.walk()

    def find(self, role: str, name: str | None = None) -> AriaNode | None:
        return next(
            (n for n in self.walk() if n.role == role and (name is None or n.name == name)), None
        )

    def find_all(self, role: str) -> list[AriaNode]:
        return [n for n in self.walk() if n.role == role]

    def text(self) -> str:
        """Visible text of this node: its name, else its value, else its children's text.
        A text named for what it shows (a desktop label: ``- text "Faktura - nazwa": K0023``)
        shows its value."""
        if self.role == "text" and self.name and self.value:
            return self.value
        if self.name:
            return self.name
        if self.value and not self.role.startswith("/"):
            return self.value
        return " ".join(t for t in (c.text() for c in self.children) if t).strip()


def parse_aria(snapshot: str) -> AriaNode:
    root = AriaNode(role="root")
    stack: list[tuple[int, AriaNode]] = [(-1, root)]
    for line in snapshot.splitlines():
        match = _LINE.match(_plain_line(line))
        if not match:
            continue
        indent = len(match.group("indent"))
        name = match.group("name")
        node = AriaNode(
            role=match.group("role"),
            name=name.replace('\\"', '"').replace("\\\\", "\\") if name is not None else None,
            value=_unquote(match.group("value")) if match.group("value") else None,
            attrs={k: v or "" for k, v in _ATTR.findall(match.group("attrs") or "")},
        )
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack[-1][1].children.append(node)
        stack.append((indent, node))
    return root


_ICONS = re.compile(r"[\ue000-\uf8ff]")
"""Icons of icon fonts: characters of Unicode's private use area. The accessibility tree
reads them out (Odoo's sort arrow after „Pracownik”), a person and the page's text do not."""


def _read(text: str) -> str:
    """A table's text as people read it, and as the recorder and the runtime do."""
    return " ".join(_ICONS.sub(" ", text).split()) if _ICONS.search(text) else text


def table_rows(table: AriaNode) -> list[dict[str, str]]:
    """Data rows of a table as {column header: cell text}; unnamed columns become '#n'."""
    return [values for _, values in table_row_nodes(table)]


def table_row_nodes(table: AriaNode) -> list[tuple[AriaNode, dict[str, str]]]:
    """Data rows of a table: each row's node and its {column header: cell text}."""
    headers: list[str] = []
    rows: list[tuple[AriaNode, dict[str, str]]] = []
    for row in table.find_all("row"):
        cells = [c for c in row.children if c.role in ("cell", "columnheader", "rowheader")]
        if cells and all(c.role == "columnheader" for c in cells):
            headers = [_read(c.text()) for c in cells]
            continue
        values = [_read(c.text()) for c in cells]
        if len(values) == 1 and len(headers) >= 2:
            continue  # one cell across the columns: "Brak pozycji", the empty table's words
        rows.append(
            (
                row,
                {
                    (headers[i] if i < len(headers) and headers[i] else f"#{i + 1}"): value
                    for i, value in enumerate(values)
                },
            )
        )
    return rows


def messages(root: AriaNode) -> list[tuple[str, str]]:
    """(role, text) of alerts, status messages and dialogs on the screen."""
    return [
        (n.role, n.text())
        for n in root.walk()
        if n.role in ("alert", "status", "dialog", "alertdialog") and n.text()
    ]
