"""What a Java window shows, as the rest of Maptelo reads screens.

The bridge gives a tree of Java roles (``push button``, ``text``, ``internal frame``...) and
names as the program sets them (``OK ALT O``, ``Main tab page Name Required``, ``Product
Context RequiredList of Values`` in Oracle Forms). Here they become what a person reads: a
button "OK", a field "Name", a field "Product Context", with ARIA roles, so that recordings
of Java programs are mapped by the same code as browser recordings (an ``aria`` text in each
screen state, locators by role and name).

Oracle Forms shows the lines of a document as rows of fields, every row's field with the same
name (a "multi-row block"). Such fields are read as a table: one row per record, one column
per field, so a step can say "the Price of the row where Product Value is 921399".
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace

from maptelo.desktop.jab import SECRET, Node, Table

ARIA_ROLE: dict[str, str] = {
    "push button": "button",
    "toggle button": "button",
    "text": "textbox",
    "password text": "textbox",
    "check box": "checkbox",
    "radio button": "radio",
    "combo box": "combobox",
    "list": "listbox",
    "list item": "option",
    "page tab": "tab",
    "page tab list": "tablist",
    "menu bar": "menubar",
    "menu": "menuitem",
    "menu item": "menuitem",
    "check box menu item": "menuitemcheckbox",
    "radio menu item": "menuitemradio",
    "popup menu": "menu",
    "table": "table",
    "tree": "tree",
    "spin box": "spinbutton",
    "slider": "slider",
    "progress bar": "progressbar",
    "tool bar": "toolbar",
    "status bar": "status",
    "dialog": "dialog",
    "alert": "alertdialog",
    "option pane": "alertdialog",
    "internal frame": "region",
    "label": "text",
    "hyperlink": "link",
    "column header": "columnheader",
}
STRUCTURE = frozenset(
    {
        "root pane",
        "layered pane",
        "glass pane",
        "panel",
        "scroll pane",
        "viewport",
        "filler",
        "split pane",
        "separator",
        "scroll bar",
        "frame",
        "window",
        "canvas",
        "unknown",
        "desktop pane",
        "desktop icon",
        "swing component",
        "awt component",
    }
)
FIELDS = frozenset({"textbox", "combobox", "checkbox", "radio", "spinbutton"})
NAMED_BY_LABEL = frozenset({"textbox", "combobox", "spinbutton"})

_TAB_PAGE = re.compile(r"^.*\btab page\s+", re.IGNORECASE)
_SUFFIXES = (
    re.compile(r"\s*List Values(?::.*)?$"),
    re.compile(r"\s*List of Values$"),
    re.compile(r"\s*Lista wartości$"),
    re.compile(r"\s*Required$"),
    re.compile(r"\s*Wymagane$"),
    re.compile(r"\s+(?:alt|mnemonic)\s+\S$", re.IGNORECASE),
)
_HINT_END = re.compile(r"[.!?](?P<tail>[^.!?]{1,40})$")


def clean_name(raw: str) -> str:
    """What a person reads as the element's name: ``OK ALT O`` -> ``OK``, ``Main tab page Name
    Required`` -> ``Name``, ``Product Context RequiredList of Values`` -> ``Product Context``,
    ``Export mnemonic E`` -> ``Export``; a long hint with the field's own label at its end (an
    Oracle search field) -> that label."""
    name = " ".join((raw or "").split())
    if not name or name == "null":
        return ""
    name = _TAB_PAGE.sub("", name)
    for _ in range(3):
        before = name
        for pattern in _SUFFIXES:
            name = pattern.sub("", name).strip()
        if name == before:
            break
    if len(name) > 60:
        hint = _HINT_END.search(name)
        if hint:
            name = hint.group("tail").strip()
    return name


def aria_role(node: Node) -> str | None:
    """The ARIA role for a Java role; None for what only holds other elements."""
    if node.role in STRUCTURE:
        return None
    return ARIA_ROLE.get(node.role)


@dataclass
class Element:
    """One thing on a Java screen a step can act on or read."""

    node: Node
    role: str
    name: str
    value: str | None = None
    frame: str | None = None
    """The innermost frame or dialog it is in (its title), None in the window itself."""
    frames: tuple[str, ...] = ()
    """Every frame and dialog it is in, outermost first."""
    modal: bool = False
    """It is in a window or frame that blocks the others (a list of values, a question)."""
    block: str | None = None
    """For a field of a multi-row block: which block (the frame and the columns)."""
    row: int | None = None
    """Its row in the block or table, 0 the first shown."""
    column: str | None = None
    cells: dict[str, str] = field(default_factory=dict)
    """The other fields' values in its row (for a rule naming the row by them)."""
    chosen: str | None = None
    """For a combo box one cannot type into: the item it holds (read from its list, which is
    not showing, or asked of the box itself); written as [chosen=…], not as a typed value."""

    @property
    def path(self) -> str:
        return self.node.path

    @property
    def enabled(self) -> bool:
        return self.node.enabled

    @property
    def checked(self) -> bool:
        return self.node.checked

    @property
    def selected(self) -> bool:
        return self.node.selected

    def describe(self) -> str:
        where = f" in {self.frame!r}" if self.frame else ""
        row = f" (row {self.row + 1})" if self.row is not None else ""
        return f'{self.role} "{self.name}"{row}{where}'


@dataclass
class Screen:
    """A Java window as it is now: its title, its frames and dialogs, its elements."""

    title: str
    hwnd: int
    nodes: list[Node]
    elements: list[Element]
    frames: list[tuple[str, Node]]
    """Frames and dialogs shown, in the tree's order (title, node)."""
    status: list[str] = field(default_factory=list)
    """What the status bar says, line by line."""
    tables: dict[str, Table] = field(default_factory=dict)

    # -- what is where -------------------------------------------------------------------------

    def active_frame(self) -> str | None:
        """The title of the frame the person works in (see ``working_frame``)."""
        frame = self.working_frame()
        return frame[0] if frame is not None else None

    def working_frame(self) -> tuple[str, Node] | None:
        """The frame the person works in: a modal one (a list of values over a form), else the
        one marked active, else the one in front."""
        modal = [f for f in self.frames if "modal" in f[1].states]
        if modal:
            return modal[-1]
        active = [f for f in self.frames if "active" in f[1].states]
        if active:
            return active[-1]
        return self.front_frame()

    def front_frame(self) -> tuple[str, Node] | None:
        """The frame in front, and inside it the one in front of its own frames. Swing marks
        none of them: its desktop pane lists them front first (benchmark: SRK with three frames
        open; Ctrl+F4 closes the first listed, wherever the focus is)."""
        level = _outermost(self.frames)
        front = None
        while level:
            front = min(level, key=lambda f: _order(f[1].path))
            level = _outermost([f for f in self.frames if _inside(f[1].path, front[1].path)])
        return front

    def outer_frames(self) -> list[tuple[str, Node]]:
        """The frames directly in the window (not inside another frame), front first."""
        return sorted(_outermost(self.frames), key=lambda f: _order(f[1].path))

    def in_working_frame(self, element: Element) -> bool:
        """The element is in the frame the person works in (or the window has no frames)."""
        frame = self.working_frame()
        return frame is None or _inside(element.path, frame[1].path)

    def by_path(self, path: str) -> Element | None:
        return next((e for e in self.elements if e.path == path), None)

    def find(
        self,
        *,
        role: str | None = None,
        name: str | None = None,
        text: str | None = None,
        column: str | None = None,
        frame: str | None = None,
        enabled_only: bool = False,
    ) -> list[Element]:
        """Elements with that role and exact name (or text inside their name or value),
        optionally in one frame. ``column``: fields of a block's column (any row)."""
        found = []
        wanted_name = _norm(name) if name is not None else None
        for element in self.elements:
            if role is not None and element.role != role:
                continue
            if wanted_name is not None and _norm(element.name) != wanted_name:
                continue
            if column is not None and _norm(element.column or "") != _norm(column):
                continue
            if text is not None:
                said = f"{element.name} {element.value or ''}"
                if _norm(text) not in _norm(said):
                    continue
            if frame is not None and element.frame != frame and frame not in element.frames:
                continue
            if enabled_only and not element.enabled:
                continue
            found.append(element)
        return found

    def modal_frames(self) -> list[str]:
        return [t for t, n in self.frames if "modal" in n.states]

    # -- the screen as text --------------------------------------------------------------------

    def aria(self, *, titles: Callable[[str], str] | None = None) -> str:
        """The screen as a Playwright accessibility snapshot would write it. ``titles``: how the
        titles of windows and frames are written (a recording writes the record's data in them as
        a pattern, so a title is not a fact of one record: benchmark D01, the customer's code in
        “Nowa wersja ceny - K0015” became the rule for a choice)."""
        lines: list[str] = []
        title_of = titles or (lambda title: title)
        by_frame: dict[str | None, list[Element]] = defaultdict(list)
        for element in self.elements:
            by_frame[element.frame].append(element)
        written_blocks: set[str] = set()

        def write(elements: list[Element], indent: str) -> None:
            for element in elements:
                if element.block is not None:
                    if element.block in written_blocks:
                        continue
                    written_blocks.add(element.block)
                    lines.extend(self._block_lines(element.block, indent))
                    continue
                if element.role == "dialog" and element.name:
                    element = replace(element, name=title_of(element.name))
                lines.append(indent + _line(element))
                table = self.tables.get(element.path) if element.role == "table" else None
                if table is not None:
                    lines.extend(_table_lines(table, indent + "  "))

        write(by_frame.get(None, []), "")
        for title, node in self.frames:
            role = "dialog" if "modal" in node.states or node.role == "dialog" else "region"
            lines.append(f"- {role} {_quote(title_of(title))}:")
            write(by_frame.get(title, []), "  ")
        if self.status:
            lines.append("- status: " + _value(" | ".join(self.status)))
        return "\n".join(lines)

    def _block_lines(self, block: str, indent: str) -> list[str]:
        cells = [e for e in self.elements if e.block == block]
        columns = list(dict.fromkeys(e.column for e in cells if e.column))
        rows: dict[int, dict[str, Element]] = defaultdict(dict)
        for e in cells:
            if e.row is not None and e.column is not None:
                rows[e.row][e.column] = e
        out = [f"{indent}- table:"]
        out.append(f"{indent}  - row:")
        out.extend(f"{indent}    - columnheader {_quote(c)}" for c in columns)
        for r in sorted(rows):
            out.append(f"{indent}  - row:")
            for c in columns:
                cell = rows[r].get(c)
                if cell is None:
                    out.append(f"{indent}    - cell")
                    continue
                # the field without its name: the column's header names it, and the cell
                # reads as what the field holds
                out.append(f"{indent}    - cell:")
                out.append(f"{indent}      {_line(cell, named=False)}")
        return out


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _value(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if one_line else '""'


def _line(element: Element, *, named: bool = True) -> str:
    attrs = []
    if element.role in ("checkbox", "radio", "menuitemcheckbox", "menuitemradio"):
        attrs.append("[checked]" if element.checked else "")
    if element.role in ("tab", "option") and element.selected:
        attrs.append("[selected]")
    if not element.enabled and element.role in FIELDS | {"button", "menuitem", "tab"}:
        attrs.append("[disabled]")
    if element.role == "combobox" and element.chosen and element.value is None:
        shown = " ".join(element.chosen.split()).replace("]", ")")
        attrs.append(f"[chosen={shown}]")
    attr = "".join(f" {a}" for a in attrs if a)
    head = f"- {element.role}" + (f" {_quote(element.name)}" if element.name and named else "")
    head += attr
    if element.role == "text":
        if element.value is not None and element.name:  # named for what it shows
            return f"- text {_quote(element.name)}: {_value(element.value)}"
        return f"- text: {_value(_label_text(element.node))}"
    if element.value is not None and element.role in FIELDS | {"textbox"}:
        return f"{head}: {_value(element.value)}"
    return head


def _table_lines(table: Table, indent: str) -> list[str]:
    out = [f"{indent}- row:"]
    out.extend(f"{indent}  - columnheader {_quote(h)}" for h in table.headers)
    for row in table.rows:
        out.append(f"{indent}- row:")
        out.extend(f"{indent}  - cell: {_value(c)}" if c else f"{indent}  - cell" for c in row)
    return out


# -- building a screen ----------------------------------------------------------------------


def build_screen(
    title: str,
    hwnd: int,
    nodes: list[Node],
    *,
    tables: dict[str, Table] | None = None,
    chosen: Mapping[str, str] | None = None,
) -> Screen:
    """The screen of one window from its tree (``Bridge.tree``). ``chosen``: the item each combo
    box holds, by the box's path (``chosen_in_lists``)."""
    by_path = {n.path: n for n in nodes}
    frames: list[tuple[str, Node]] = []
    elements: list[Element] = []
    status: list[str] = []
    hidden_under: list[str] = []
    for node in nodes:
        if any(node.path.startswith(p + "/") for p in hidden_under):
            continue
        if node.role in ("internal frame", "dialog", "option pane") and node.depth > 0:
            if node.showing and node.role != "option pane":
                frames.append((clean_name(node.name) or node.role, node))
            continue
        if node.role == "status bar":
            status.extend(_status_texts(node, nodes))
            hidden_under.append(node.path)
            continue
        role = aria_role(node)
        if role is None or not node.showing:
            continue
        if node.role == "label" and _parent_role(node, by_path) == "list":
            role = "option"  # a row of a list (Oracle's lists of values are labels)
        # what a status line shows: its text, or, for a Swing label whose text the bridge does
        # not read (only an HTML label has it), its name, which is that text (benchmark WCR)
        shown = _label_text(node) if role == "text" else ""
        if role == "text" and _status_line(node, nodes[0]) and shown.strip():
            status.append(" ".join(shown.split()))
            continue
        if role == "text" and not _label_text(node).strip():
            continue  # a label that shows nothing (its name is for a reader, not on screen)
        if (
            role == "textbox"
            and not node.name.strip()
            and not ({"focusable", "editable"} & node.states)
        ):
            continue  # a prompt drawn as a field (Oracle Forms' column headings)
        if role in ("menuitem", "menu") and _in_closed_menu(node, by_path):
            continue
        chain = _frames_of(node, by_path)
        element = Element(
            node=node,
            role=role,
            name=clean_name(node.name),
            value=_value_of(node, role, nodes),
            frame=chain[-1][0] if chain else None,
            frames=tuple(t for t, _ in chain),
            modal=any("modal" in n.states for _, n in chain),
            chosen=(chosen or {}).get(node.path) if role == "combobox" else None,
        )
        if role in ("listbox", "table", "combobox", "menubar", "tablist", "toolbar"):
            pass  # their children are elements of their own
        elements.append(element)
    _mark_blocks(elements)
    return Screen(title, hwnd, nodes, elements, frames, status, dict(tables or {}))


def chosen_in_lists(
    nodes: list[Node],
    read: Callable[[str], list[Node]],
    held: Callable[[str, int], list[int]] | None = None,
) -> dict[str, str]:
    """The item each showing combo box holds, for the boxes whose own text does not say (one
    cannot type into them: WCR's „Cena za”, „Kanał sprzedaży”); ``read`` gives the elements
    under a path, hidden ones too (the list is not showing). By the box's path.

    The list knows the item only once it has been opened: Swing's list forgets it when the
    program gives the box new items, and learns it again when it opens. Where the list shows
    none, ``held`` asks the box itself which of its items (by index, of ``count``) it holds,
    as the box's own selection says (benchmark M1: „Cena za” follows the item's unit, so the
    form's „1 szt.” left as it was looked like nothing, and the step chosen only for „1000
    szt.” went to a person)."""
    chosen: dict[str, str] = {}
    for node in nodes:
        if node.role != "combo box" or not node.showing or (node.text or "").strip():
            continue
        try:
            under = read(node.path)
        except Exception:  # gone or busy: the box stays without it
            continue
        listed = next((n for n in under if n.role == "list"), None)
        if listed is None:
            continue
        items = {
            n.path.rpartition("/")[2]: n
            for n in under
            if n.depth == listed.depth + 1 and n.is_under(listed)
        }
        item = next((n for n in items.values() if n.selected), None)
        if item is None and held is not None and node.selectable and listed.children:
            try:
                indexes = held(node.path, listed.children)
            except Exception:  # gone or busy: the box stays without it
                indexes = []
            item = items.get(str(indexes[0])) if indexes else None
        if item is not None and clean_name(item.name):
            chosen[node.path] = clean_name(item.name)
    return chosen


def _label_text(node: Node) -> str:
    """What a label shows: its text when the bridge reads it, else its name."""
    return node.text if node.text is not None else node.name


def status_labels(screen: Screen) -> set[tuple[str, str]]:
    """The labels a screen shows as its status line, as the bridge names them when they change
    (role, name): only named ones, an unnamed label could be any."""
    if not screen.nodes:
        return set()
    root = screen.nodes[0]
    return {
        (node.role, node.name)
        for node in screen.nodes
        if node.role == "label" and node.name.strip() and _status_line(node, root)
    }


def _status_line(node: Node, root: Node) -> bool:
    """A label along the bottom of the window, wider than a third of it: the status line of
    a program that does not call it a status bar (what was saved, what went wrong)."""
    _, wy, ww, wh = root.box
    _, y, w, h = node.box
    return ww > 0 and wh > 0 and w > ww / 3 and y + h >= wy + wh * 0.9 and y >= wy + wh * 0.8


def _parent_role(node: Node, by_path: dict[str, Node]) -> str | None:
    parent = by_path.get(node.path.rpartition("/")[0])
    return parent.role if parent is not None else None


def _order(path: str) -> tuple[int, ...]:
    return tuple(int(part) for part in path.split("/") if part.isdigit())


def _inside(path: str, outer: str) -> bool:
    return path.startswith(outer + "/")


def _outermost(frames: list[tuple[str, Node]]) -> list[tuple[str, Node]]:
    return [f for f in frames if not any(_inside(f[1].path, o[1].path) for o in frames)]


def _frames_of(node: Node, by_path: dict[str, Node]) -> list[tuple[str, Node]]:
    chain = []
    parts = node.path.split("/")
    for i in range(1, len(parts)):
        parent = by_path.get("/".join(parts[:i]))
        if parent is not None and parent.role in ("internal frame", "dialog") and parent.depth > 0:
            chain.append((clean_name(parent.name) or parent.role, parent))
    return chain


def _in_closed_menu(node: Node, by_path: dict[str, Node]) -> bool:
    """A menu item of a menu that is not open: the bridge lists it, a person does not see it."""
    parts = node.path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        parent = by_path.get("/".join(parts[:i]))
        if parent is None:
            continue
        if parent.role == "popup menu":
            return not parent.showing or "visible" not in parent.states
        if parent.role == "menu bar":
            return False
    return False


def _status_texts(bar: Node, nodes: list[Node]) -> list[str]:
    texts = []
    for node in nodes:
        if node.is_under(bar) and node.role == "label":
            said = " ".join(node.name.split())
            if said and said not in ("<OSC>",):
                texts.append(said)
    return texts


def _value_of(node: Node, role: str, nodes: list[Node]) -> str | None:
    if role == "text":
        # a label named for what it shows ("Faktura - nazwa" beside the invoice's number): its
        # text is a value, as a display item of Oracle Forms shows one under its prompt
        shown = (node.text or "").strip()
        if shown and node.name.strip() and _norm(shown) != _norm(node.name):
            return " ".join(shown.split())
        return None
    if role == "textbox":
        if node.role == "password text":
            return SECRET if node.text else ""
        return node.text if node.text is not None else None
    if role == "combobox":
        if node.text:
            return node.text
        chosen = [
            n for n in nodes if n.is_under(node) and n.selected and n.role in ("label", "list item")
        ]
        return chosen[0].name if chosen else None
    if role == "spinbutton":
        return node.text
    return None


def _mark_blocks(elements: list[Element]) -> None:
    """Fields named alike in one frame, one above the other: the rows of a multi-row block."""
    groups: dict[tuple[str | None, str, str], list[Element]] = defaultdict(list)
    for element in elements:
        if element.role in FIELDS and element.name:
            groups[(element.frame, element.role, _norm(element.name))].append(element)
    columns: dict[str | None, list[list[Element]]] = defaultdict(list)
    for (frame, _, _), members in groups.items():
        for col in _by_left_edge(members):
            ys = {e.node.box[1] for e in col}
            if len(col) >= 2 and len(ys) == len(col):
                columns[frame].append(sorted(col, key=lambda e: e.node.box[1]))
    for frame, cols in columns.items():
        # columns of one block have their rows at the same heights, give or take a few pixels
        # (benchmark D06: the date columns of the lines were split off by rounding)
        blocks: list[tuple[list[int], list[list[Element]]]] = []
        for col in sorted(cols, key=lambda c: c[0].node.box[0]):
            heights = [e.node.box[1] for e in col]
            for reference, joined in blocks:
                if len(reference) == len(heights) and all(
                    abs(a - b) <= 6 for a, b in zip(reference, heights, strict=True)
                ):
                    joined.append(col)
                    break
            else:
                blocks.append((heights, [col]))
        for key, block_cols in blocks:
            block_id = f"{frame or ''}#{key[0]}"
            for col in block_cols:
                for row, element in enumerate(col):
                    element.block = block_id
                    element.row = row
                    element.column = element.name
    fill_block_cells(elements)


def _by_left_edge(members: list[Element]) -> list[list[Element]]:
    """Fields named alike, one list per left edge (give or take a few pixels): a field of the
    same name elsewhere in the frame is not a row of the column (benchmark D06: the price
    list's own Start Date in its header, over the Start Date column of its lines)."""
    out: list[list[Element]] = []
    for element in sorted(members, key=lambda e: e.node.box[0]):
        for col in out:
            if abs(col[0].node.box[0] - element.node.box[0]) <= 6:
                col.append(element)
                break
        else:
            out.append([element])
    return out


def fill_block_cells(elements: list[Element]) -> None:
    """Each field of a block knows its row's values as the fields hold them now, left to right
    (again after a recording set fields back to what they held before the act)."""
    members = sorted(
        (e for e in elements if e.block is not None and e.row is not None),
        key=lambda e: (e.block or "", e.row or 0, e.node.box[0]),
    )
    rows: dict[tuple[str, int], dict[str, str]] = defaultdict(dict)
    for e in members:
        rows[(e.block or "", e.row or 0)][e.name] = e.value or ""
    for e in members:
        e.cells = rows[(e.block or "", e.row or 0)]


def walk_elements(screen: Screen, roles: Iterable[str]) -> Iterator[Element]:
    wanted = set(roles)
    return (e for e in screen.elements if e.role in wanted)


def field_beside(
    screen: Screen,
    box: tuple[int, int, int, int],
    *,
    within: int | None = None,
    enabled_only: bool = False,
) -> Element | None:
    """The field a button stands beside, by where both stand: the nearest field on its left in
    its line, ending before the button's middle (Oracle Forms' "…" of a list of values or of a
    calendar stands at its field's right edge). ``within``: at most so many pixels between the
    field's end and the button."""
    x, y, w, h = box
    middle = y + h / 2
    line = [
        e
        for e in screen.elements
        if e.role == "textbox"
        and (e.enabled or not enabled_only)
        and e.node.box[2] > 0
        and abs((e.node.box[1] + e.node.box[3] / 2) - middle) <= h / 2
        and e.node.box[0] < x
        and e.node.box[0] + e.node.box[2] <= x + w / 2
        and (within is None or x - (e.node.box[0] + e.node.box[2]) <= within)
    ]
    return max(line, key=lambda e: e.node.box[0] + e.node.box[2]) if line else None
