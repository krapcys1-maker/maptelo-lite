"""Recording demonstrations in Java programs (Oracle Forms, Swing) through the Java
Access Bridge, into the same traces a browser recording makes.

The bridge says what happened to which element: focus moved, a field's text changed, an
element was clicked, a box got ticked, a list's choice changed, a frame or a window opened.
Keys are not among what it says. They are told by what they did, as a colleague watching
would: text typed into a field and then the screen reacting while the field keeps the focus
is Enter; a field left for the next one is a Tab (the value is committed, nothing more is
recorded, as in a browser); a question gone without a click is Escape. On the computer of the
person recording, the keys of navigation (Enter, Escape, Tab, arrows, F keys) are also read as
they are pressed, never the letters (what is typed is read from the field).

Each action keeps what the person saw of its element (role, name, the frame it is in, the
row of a block of lines) and the screen before and after it (the window as an accessibility
snapshot, a screenshot), so mapping and building a model work as for a browser.
"""

from __future__ import annotations

import contextlib
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from maptelo.desktop.jab import Bridge, Node, Window
from maptelo.desktop.screen import (
    Element,
    Screen,
    build_screen,
    clean_name,
    fill_block_cells,
    status_labels,
)
from maptelo.model.schema import Locator
from maptelo.trace.io import TraceWriter
from maptelo.trace.schema import (
    DataRef,
    ElementInfo,
    RowContext,
    TraceEnd,
    TraceEvent,
    TraceHeader,
    TraceState,
)

SCHEME = "java"
TEXT_ROLES = frozenset({"text", "password text", "spin box"})
CLICKABLE = frozenset(
    {
        "push button",
        "toggle button",
        "check box",
        "radio button",
        "page tab",
        "menu item",
        "check box menu item",
        "radio menu item",
        "hyperlink",
    }
)
CHOOSERS = frozenset({"combo box"})
BUTTONS = frozenset({"push button", "toggle button"})
"""Pressed then released: a click, even when the bridge cannot tell the click (see Interpreter)."""
LIST_ROLES = frozenset({"list", "table", "tree"})


def title_template(title: str) -> str:
    """A window's or frame's title without what names one record or person: ``Nowa wersja
    ceny - K0010`` -> ``Nowa wersja ceny - *``; ``Purchase Orders - 4500123`` -> ``Purchase
    Orders - *``. Parts with digits become ``*``."""
    parts = re.split(r"(\s+[\u2013\u2014-]\s+|\s*\[|\]\s*)", title)
    out = []
    for part in parts:
        if any(ch.isdigit() for ch in part) and not re.fullmatch(r"\s*[\[\]]\s*", part):
            out.append("*")
        else:
            out.append(part)
    return "".join(out).strip()


def screen_url(app: str, frame: str | None) -> str:
    """The address a Java screen gets in a trace: ``java://<program>/<frame title>``."""
    path = title_template(frame) if frame else ""
    return f"{SCHEME}://{app}/{path}"


def program_name(title: str) -> str:
    """A short name of the program from its main window's title (``SRK 4.2.7 - System...``
    -> ``srk``; ``Oracle Applications - XYZ`` -> ``oracle-applications``)."""
    first = re.split(r"\s+[\u2013\u2014-]\s+|\d", title, maxsplit=1)[0].strip()
    slug = re.sub(r"[^a-z0-9]+", "-", first.casefold()).strip("-")
    return slug or "java"


def display_name(title: str) -> str:
    """The program as people name it, from its main window's title: ``SRK 4.2.7 - System
    Rozliczeń...`` -> ``SRK``; ``Oracle Applications - XYZ`` -> ``Oracle Applications``."""
    first = re.split(r"\s+[\u2013\u2014-]\s+", title, maxsplit=1)[0]
    words = [w for w in first.split() if not any(ch.isdigit() for ch in w)]
    return " ".join(words) or title.strip() or "Java"


@dataclass(frozen=True)
class JavaRecorderOptions:
    window: str = ""
    """A part of the main window's title (the program to record)."""
    pid: int | None = None
    process: str | None = None
    title: str | None = None
    """The process as the person named it, when that is not its folder name."""
    note: str | None = None
    screenshots: bool = True
    data: Path | None = None
    sheet: str | None = None
    private: bool = False
    settle_ms: int = 400
    max_settle_ms: int = 5000
    raw_events: bool = False
    """Also keep what the bridge said, event by event (bridge-events.jsonl), to find out
    why an action was or was not told from them."""
    java_dirs: tuple[Path, ...] = ()
    """Where the program's own Java is (its bridge library first): a program with a Java of
    its own (Oracle Forms) has it in no folder the bridge is looked for in otherwise."""


# -- what happened, from the bridge's events ---------------------------------------------------


@dataclass
class Seen:
    """An element as an event described it."""

    node: Node
    chain: list[tuple[str, str]]
    window: int

    @property
    def key(self) -> tuple[int, str]:
        return (self.window, self.node.path)

    @property
    def frame(self) -> str | None:
        for role, name in self.chain:
            if role in ("internal frame", "dialog", "option pane") and name:
                return clean_name(name)
        return None

    @classmethod
    def of(cls, source: dict[str, Any] | None) -> Seen | None:
        if not source or "node" not in source or "path" not in source["node"]:
            return None
        chain = [(str(r), str(n)) for r, n in source.get("chain") or []]
        return cls(Node.from_dict(source["node"]), chain, int(source.get("window") or 0))


_WINDOW = ("window", "")
"""What a window opening or closing is told as among the program's reactions."""

UNKNOWN = "\u0000unknown"
"""A field's text before typing, when no screen showed it."""


@dataclass
class Editing:
    seen: Seen
    start: str | None
    last: str | None = None
    changed: bool = False
    changed_at: float = 0.0
    table_edit: tuple[float, Seen, dict[str, Any]] | None = None
    left_at: float | None = None
    """When the person, done typing, pressed the mouse on something else: the program reacting
    from then on answers the mouse, not an Enter."""


@dataclass
class Act:
    """An action the person made, told from the events."""

    type: str
    t: float
    seen: Seen | None
    value: str | None = None
    option_label: str | None = None
    secret: bool = False
    menu: str | None = None
    cell: str | None = None
    """For a click in a table: the text of the cell the table says was chosen."""
    row: RowContext | None = None
    column: str | None = None
    cell_index: int | None = None


@dataclass
class Interpreter:
    """Turns the bridge's events into actions (``acts``). Pure: fed events and ticks."""

    acts: list[Act] = field(default_factory=list)
    focus: Seen | None = None
    editing: Editing | None = None
    last_click: tuple[float, Seen] | None = None
    activity_at: float = -1.0
    reacted_at: float = -1.0
    """The program's first reaction after the last typing into the field being edited."""
    retyped_s: float = 0.3
    """A field's text written again unchanged this long after the last typing is the
    program's doing (the bridge reads a field's text when it tells the change: a quick burst
    of typing shows the last text in every event)."""
    pressed: tuple[float, Seen] | None = None
    """A button pressed whose click has not come yet."""
    lost_click_s: float = 0.6
    """A press without its click this long after is a click whose element went away."""
    press_s: float = 0.08
    """What happens this close before a press is the press's own doing (a list opening, a
    button armed): the bridge may say it before it says the press."""
    menu_open: str | None = None
    combo: Seen | None = None
    combo_choice: str | None = None
    combo_at: float = 0.0
    status_labels: set[tuple[str, str]] = field(default_factory=set)
    """The labels that are the program's status line (role, name): what they say after a field
    was typed into answers an Enter (SRK: "Faktura: brak pozycji „…”"), it does not echo the
    typing."""
    table_edit: tuple[float, Seen, dict[str, Any]] | None = None
    list_choice: dict[tuple[int, str], tuple[Seen, str]] = field(default_factory=dict)
    keys_seen: bool = False
    """Navigation keys are read from the keyboard: nothing has to be told from reactions."""
    react_s: float = 0.25
    react_window_s: float = 1.0
    """A window opened while a field was typed into, nothing else reacting: a click the bridge
    tells late (it was reading the new window) may still come this long."""
    window_only: bool = False
    """The program's reaction to the typing so far is only a window that opened."""
    known: dict[tuple[int, str], tuple[float, str | None]] = field(default_factory=dict)
    """What fields held on the last screen captured (their text before the person typed)."""
    described: dict[tuple[str, str], tuple[float, Seen]] = field(default_factory=dict)
    """The latest full description of each (role, name): a button that closes its question
    is described after it closed, without the question around it."""

    def remember(self, window: int, values: dict[str, str | None], t: float) -> None:
        """The fields' values on a screen just captured (finished at ``t``), by their paths."""
        for path, value in values.items():
            self.known[(window, path)] = (t, value)

    def _start(self, seen: Seen, t: float) -> str | None:
        """A field's text before the person typed: from a screen captured before the field got
        the focus; a screen read while the person was already typing does not tell it."""
        known = self.known.get(seen.key)
        if known is None or known[0] >= t:
            return UNKNOWN
        return known[1]

    def feed(self, event: dict[str, Any]) -> None:
        kind = event.get("kind")
        t = float(event.get("t") or 0.0)
        seen = self._complete(Seen.of(event.get("source")), t)
        if kind == "key":
            self._key(str(event.get("key")), t)
            return
        if kind == "windows_changed":
            self._activity(t, _WINDOW)
            return
        if seen is None:
            if kind in ("visible_data_changed", "child_changed"):
                told = (event.get("source") or {}).get("node") or {}  # a label: role and name only
                key = (str(told.get("role") or ""), str(told.get("name") or ""))
                self._activity(t, key if any(key) else None)
            return
        node = seen.node
        if node.role == "table" and kind in ("active_descendant", "child_changed"):
            child = event.get("new") or {}
            if child and (kind == "active_descendant" or self.table_edit is None):
                self.table_edit = (t, seen, child)
        if kind == "focus":
            self._focus(seen, t)
        elif kind == "text_changed":
            self._text(seen, t)
        elif kind == "mouse_clicked":
            self._went_on(t, seen)
            if self.pressed is not None and self.pressed[1].key == seen.key:
                self.pressed = None  # its click came
            self._click(seen, t)
        elif kind == "mouse_pressed":
            self._went_on(t, seen)
            self._lost_click()
            if node.role in BUTTONS:
                self.pressed = (t, seen)
            if node.role.endswith("menu item"):
                self._click(
                    seen, t
                )  # a menu item says it was pressed; its popup is gone at release
        elif kind == "state_changed":
            self._state(seen, t, str(event.get("old") or ""), str(event.get("new") or ""))
        elif kind == "active_descendant":
            new = event.get("new") or {}
            if node.role in CHOOSERS and new.get("name"):
                self.combo, self.combo_choice = seen, str(new["name"])
                self.combo_at = t
            elif node.role in LIST_ROLES and new.get("name"):
                self.list_choice[seen.key] = (seen, str(new["name"]))
        elif kind == "menu_selected" and node.role == "menu":
            self.menu_open = clean_name(node.name)
        elif kind in ("visible_data_changed", "child_changed", "selection_changed") and not (
            self._is_focus(seen)
        ):
            self._activity(t, (node.role, node.name))

    def tick(self, now: float) -> None:
        """Time passed: text typed into a field, then the screen reacting while the field
        kept the focus, was Enter."""
        wait = self.react_window_s if self.window_only else self.react_s
        if self.activity_at >= 0 and now - self.activity_at >= wait:
            self._enter_if_reacted(now)
        if self.pressed is not None and now - self.pressed[0] >= self.lost_click_s:
            self._lost_click()

    def _lost_click(self) -> None:
        """A button pressed whose click the bridge never told: it closed its window or frame
        before the release could be told (benchmark D06: Find in the Find window). It was
        clicked all the same."""
        if self.pressed is None:
            return
        t, seen = self.pressed
        self.pressed = None
        self._click(seen, t)

    def _went_on(self, t: float, seen: Seen | None = None) -> None:
        """The person goes on with the mouse. The program reacting after the field was typed
        into and before this press was Enter, however quickly the person went on (benchmark:
        a colleague clicked the next button the moment the customer's prices loaded, so the
        quiet the tick waits for never came). A check the program makes when the field loses
        the focus reacts after the press, not before it; so does what the pressed button does,
        though the bridge may tell it before the click (benchmark D04: the list of people
        filled 1 ms after the press on Znajdź, its click told 95 ms later). A window that alone
        opened before a press in the window being typed into was told is that press's doing as
        well: the bridge was reading the new window (benchmark D04: the question of SRK seen
        107 ms before the press on Zapisz); a press in the new window keeps the Enter."""
        edit = self.editing
        late = (
            edit is not None
            and edit.changed
            and self.window_only
            and self.reacted_at >= 0
            and t - self.reacted_at <= self.react_window_s
            and seen is not None
            and seen.window == edit.seen.window
            and seen.key != edit.seen.key
        )
        if late:
            self.reacted_at = -1.0  # the window answered this press, not the typing
        else:
            self._enter_if_reacted(t - self.press_s)
        if (
            edit is not None
            and edit.changed
            and edit.left_at is None
            and (seen is None or seen.key != edit.seen.key)
        ):
            edit.left_at = t

    def _enter_if_reacted(self, before: float) -> None:
        if self.keys_seen:
            return
        edit = self.editing
        if (
            edit is not None
            and edit.changed
            and edit.changed_at < self.reacted_at <= before
            and (self.last_click is None or self.last_click[0] < edit.changed_at)
            and (edit.left_at is None or self.reacted_at < edit.left_at - self.press_s)
        ):
            self._flush(edit.changed_at)
            self.acts.append(Act("press", self.reacted_at, edit.seen, value="Enter"))
            self.activity_at = self.reacted_at = -1.0

    # -- the events ------------------------------------------------------------------------------

    def _complete(self, seen: Seen | None, t: float) -> Seen | None:
        """The element with what was seen of it before, when this event came after its window
        closed (the bridge then knows neither the window nor the question around it)."""
        if seen is None:
            return None
        if not seen.window and seen.node.path == "0" and self.table_edit is not None:
            at, table, _child = self.table_edit
            editing_this = (
                self.focus is not None and self.focus.node.path == table.node.path + "/@editor"
            )
            if (t - at < 2.0 or editing_this) and seen.node.role in TEXT_ROLES | {"check box"}:
                return Seen(
                    replace(seen.node, path=table.node.path + "/@editor"),
                    table.chain,
                    table.window,
                )
        key = (seen.node.role, seen.node.name)
        if seen.window and seen.frame is not None:
            self.described[key] = (t, seen)
            return seen
        earlier = self.described.get(key)
        if earlier is not None and t - earlier[0] < 10.0:
            return Seen(seen.node, earlier[1].chain, earlier[1].window or seen.window)
        if seen.window:
            self.described[key] = (t, seen)
        return seen

    def _is_focus(self, seen: Seen) -> bool:
        return self.focus is not None and self.focus.key == seen.key

    def _activity(self, t: float, source: tuple[str, str] | None = None) -> None:
        self.activity_at = max(self.activity_at, t)
        if source is not None and source[0] == "label" and source not in self.status_labels:
            # a label redrawn (a total recounted as the PO is typed, a hint) echoes the typing:
            # an Enter rewrites the field, fills others, a table, a window (benchmark D03); the
            # status line answers it (benchmark D04: an invoice number it does not know)
            return
        edit = self.editing
        if edit is not None and edit.changed and t > edit.changed_at:
            if self.reacted_at < 0:
                self.reacted_at = t
                self.window_only = source == _WINDOW
            elif source != _WINDOW:
                self.window_only = False

    def _focus(self, seen: Seen, t: float) -> None:
        if self.focus is not None and self.focus.key == seen.key:
            return
        if self.editing is not None and self.editing.seen.key != seen.key:
            self._flush(t)
        if self.combo is not None and self.combo.key != seen.key:
            self._choose_combo(t)
        self.focus = seen
        if seen.node.role in TEXT_ROLES:
            self.editing = self._new_edit(seen, t)
        else:
            self.editing = None

    def _text(self, seen: Seen, t: float) -> None:
        mine = self._is_focus(seen) or (
            self.last_click is not None
            and self.last_click[1].key == seen.key
            and t - self.last_click[0] < 1.0
        )
        if not mine or seen.node.role not in TEXT_ROLES:
            self._activity(t, (seen.node.role, seen.node.name))
            return
        if self.editing is None or self.editing.seen.key != seen.key:
            self.editing = self._new_edit(seen, t)
        edit = self.editing
        if edit.changed and seen.node.text == edit.last and t - edit.changed_at >= self.retyped_s:
            # the field set again to what it shows, a while after the typing: the program
            # did it (benchmark D05: Enter in the customer's field, SRK writes the code back)
            self._activity(t)
            if self.reacted_at < 0:
                self.reacted_at = t
            return
        self.editing.seen = seen
        self.editing.last = seen.node.text
        # the start is unknown when the field had not been seen; a text change of the field
        # with the focus is then the person's typing
        start = self.editing.start
        self.editing.changed = start is UNKNOWN or self.editing.last != start
        self.editing.changed_at = t
        self.editing.left_at = None  # typing again: the mouse went back to the field
        self.reacted_at = -1.0

    def _click(self, seen: Seen, t: float) -> None:
        node = seen.node
        if self.combo is not None and self.combo.key != seen.key:
            self._choose_combo(t)
        last = self.acts[-1] if self.acts else None
        if (
            node.role == "table"
            and last is not None
            and last.type in ("check", "uncheck")
            and last.seen is not None
            and last.seen.key == seen.key
            and t - last.t < 0.5
        ):
            return
        self.last_click = (t, seen)
        if node.role in TEXT_ROLES:
            return  # into a field: what is typed there is the step
        if node.role == "menu":
            self.menu_open = clean_name(node.name)
            return
        if node.role in CHOOSERS:
            self.combo = seen
            return
        if self.editing is not None and self.editing.seen.key != seen.key:
            self._flush(t)
        if node.role in ("label", "list item") and self._in_list(seen):
            self.acts.append(Act("click", t, seen, value=None))
            return
        if node.role in CLICKABLE or node.role in ("label", "list item", "table"):
            last = self.acts[-1] if self.acts else None
            if (
                last is not None
                and last.type == "click"
                and last.seen is not None
                and last.seen.node.role == node.role
                and last.seen.node.name == node.name
                and t - last.t < 0.5
            ):
                return  # pressed, then clicked: one click
            menu = self.menu_open if node.role.endswith("menu item") else None
            chosen = self.list_choice.get(seen.key) if node.role == "table" else None
            cell = chosen[1] if chosen is not None else None
            self.acts.append(Act("click", t, seen, menu=menu, cell=cell))
            if node.role.endswith("menu item"):
                self.menu_open = None

    def _in_list(self, seen: Seen) -> bool:
        return seen.node.role in ("label", "list item")

    def _state(self, seen: Seen, t: float, old: str, new: str) -> None:
        node = seen.node
        if node.role in ("check box", "radio button", "toggle button", "check box menu item"):
            if "checked" in (old, new):
                kind = "check" if new == "checked" else "uncheck"
                if node.path.endswith("/@editor") and self.table_edit is not None:
                    _, table, child = self.table_edit
                    index = child.get("index")
                    self.acts.append(Act(kind, t, table, cell_index=index))
                    return
                last = self.acts[-1] if self.acts else None
                if (
                    last is not None
                    and last.type == "click"
                    and last.seen is not None
                    and (last.seen.key == seen.key)
                ):
                    self.acts[-1] = Act(kind, last.t, seen)
                elif self._is_focus(seen):
                    self.acts.append(Act(kind, t, seen))  # the space key on a focused box
            return
        if node.role == "page tab" and new == "selected":
            last = self.acts[-1] if self.acts else None
            if not (last and last.seen and last.seen.key == seen.key):
                self.acts.append(Act("click", t, seen))

    def _key(self, key: str, t: float) -> None:
        self.keys_seen = True
        if key == "Tab" or key == "Shift+Tab":
            self._flush(t)
            return
        if key in ("Enter", "Escape", "F11", "Ctrl+F11", "ArrowDown", "ArrowUp", "PageDown"):
            target = self.focus
            self._flush(t)
            self.acts.append(Act("press", t, target, value=key))

    def _new_edit(self, seen: Seen, t: float) -> Editing:
        cell = self.table_edit
        if cell is not None and (
            seen.window != cell[1].window or seen.node.path != cell[1].node.path + "/@editor"
        ):
            cell = None
        return Editing(seen, self._start(seen, t), table_edit=cell)

    def _flush(self, t: float) -> None:
        edit = self.editing
        if edit is None or not edit.changed:
            return
        secret = edit.seen.node.role == "password text"
        self.acts.append(
            Act(
                "fill",
                min(t, edit.changed_at or t),
                edit.table_edit[1] if edit.table_edit else edit.seen,
                value=None if secret else edit.last,
                secret=secret,
                cell=(edit.table_edit[2].get("name") if edit.table_edit else None),
                cell_index=(edit.table_edit[2].get("index") if edit.table_edit else None),
            )
        )
        edit.start = edit.last
        edit.changed = False

    def _choose_combo(self, t: float) -> None:
        if self.combo is not None and self.combo_choice:
            self.acts.append(
                Act(
                    "select",
                    self.combo_at or t,
                    self.combo,
                    value=self.combo_choice,
                    option_label=self.combo_choice,
                )
            )
        self.combo = None
        self.combo_choice = None
        self.combo_at = 0.0

    def finish(self, t: float) -> None:
        self._lost_click()
        self._flush(t)
        self._choose_combo(t)

    def take(self) -> list[Act]:
        out, self.acts = self.acts, []
        return out


# -- element descriptions ---------------------------------------------------------------------


def _placed(box: tuple[int, int, int, int]) -> bool:
    """A real place on the screen (the bridge says -1 for each part when it has none)."""
    return box[2] > 0 and box[3] > 0


_NAMED_CONTROLS = frozenset(
    {"button", "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "checkbox", "radio", "link"}
)
"""Controls named by what they say: another name is another control."""


def _another(node: Node, element: Element) -> bool:
    """Whether the element a screen has at a node's path is another one than the node: of
    another kind, or a control saying something else."""
    from maptelo.desktop.screen import aria_role

    expected = aria_role(node)
    if expected is not None and node.role != "label" and element.role != expected:
        return True  # a label is text or a list's option, as its parent makes it
    told = clean_name(node.name)
    return bool(told) and expected in _NAMED_CONTROLS and element.name != told


def element_info(
    seen: Seen, screen: Screen | None, *, toolbar_index: int | None = None
) -> ElementInfo:
    """What the trace keeps of an element: role and name as a person reads them, the frame,
    the row of a block, and the ways to find it again."""
    from maptelo.desktop.screen import aria_role

    node = seen.node
    element: Element | None = screen.by_path(node.path) if screen is not None else None
    if screen is not None and element is not None and _another(node, element):
        # the same path is another element in that screen: a menu open when it was read stands
        # first in it (EBS „File > Save” read as a toolbar button without a name, the
        # clean-Windows Lite film of 13.10); the element the bridge names, else none
        told = clean_name(node.name)
        alike = [e for e in screen.elements if e.role == aria_role(node) and e.name == told]
        element = next((e for e in alike if _placed(e.node.box)), None) if told else None
    role = element.role if element is not None else (aria_role(node) or node.role)
    if node.role == "label" and (element is None or element.role == "option"):
        role = "option"
    name = element.name if element is not None else clean_name(node.name)
    candidates: list[Locator] = []
    if role and name:
        if element is not None and element.column is not None:
            candidates.append(Locator(role=role, name=name, column=element.column))
        candidates.append(Locator(role=role, name=name))
    if role in ("textbox", "combobox", "spinbutton") and name:
        candidates.append(Locator(label=name))
    css = None
    if not name and toolbar_index is not None:
        css = f"toolbar button #{toolbar_index}"
        candidates.append(Locator(css=css))
    row = None
    column = None
    if element is not None and element.row is not None:
        row = RowContext(table=None, cells=dict(element.cells), index=element.row)
        column = element.column
    kind = "password" if node.role == "password text" else None
    # where it is on the screen: the bridge has no place for an element whose window closed
    # as it was clicked („Tak” in a question); the screen read before the act has it
    box = node.box if _placed(node.box) else None
    if box is None and element is not None and _placed(element.node.box):
        box = element.node.box
    return ElementInfo(
        tag=f"java:{node.role}",
        type=kind,
        role=role,
        name=name or None,
        label=name if role in ("textbox", "combobox", "spinbutton") and name else None,
        text=name if role in ("button", "menuitem", "tab", "option", "link") and name else None,
        title=clean_name(node.description) or None,
        css=css,
        bbox=box,
        row=row,
        column=column,
        dialog=title_template(seen.frame) if seen.frame else None,
        candidates=candidates,
    )


# -- the recorder --------------------------------------------------------------------------------


def new_recording_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)


class JavaRecorder:
    """Records one demonstration in a Java program into ``folder``.

    ``start()`` finds the program's window and writes the first screen; ``pump()`` turns what
    happened since into trace events (call it often, or use ``record_until``); ``stop()``
    finishes the trace.

    Every time in the trace is the bridge's clock from the start, so actions and screens are
    in the order they happened. The screen after an action is the one the person saw before
    going on: it is read as soon as the person starts the next thing (a click, typing into a
    field), and a field typed into after that moment shows what it held at it.
    """

    HUMAN_GAP = 0.12
    """A click or typing this long after an action is the person going on, not its effect."""
    WINDOW_SETTLE = 0.15
    """A window an action brought up is read this long after it opened, before the person
    answers it (a question answered at once would leave no screen of it in the trace)."""

    def __init__(self, folder: Path, options: JavaRecorderOptions, bridge: Bridge | None = None):
        self.folder = folder
        self.options = options
        self.bridge = bridge
        self._own_bridge = bridge is None
        self.interpreter = Interpreter()
        self.writer: TraceWriter | None = None
        self.main: Window | None = None
        self.app = "java"
        self._seq = 0
        self._states = 0
        self._last_state: str | None = None
        self._pending: list[tuple[Act, str | None]] = []
        self._windows: dict[int, Window] = {}
        self._depth: dict[int, int] = {}
        self._screens: dict[int, Screen] = {}
        self._t0 = 0.0
        self._keys: Any = None
        self._buffer: list[dict[str, Any]] = []
        """Events that came while a screen was read: taken in the next pump."""
        self._texts: dict[tuple[int, str], list[tuple[float, str | None]]] = {}
        """Each field's text as it changed (bridge time), to read a screen as it was."""
        self._human: list[float] = []
        self._human_windows: dict[float, int] = {}
        """Where the next action began, even if its click arrives after a new dialog."""
        self._state_screens: dict[str, Screen] = {}
        self._worked_in: str | None = None
        """The frame of the main window the person last did something in."""
        """The screens of the states written, by state: an act's element is read on the screen
        before it (its row as it was, not as the form and the person left it)."""
        self._last_screen: Screen | None = None
        self._captured_at = 0.0
        """When the last screen was taken (bridge time): a window opened since then is one the
        act opened, though the bridge may tell of the click after the window showed."""
        """When the person clicked or typed (bridge time)."""
        self._last_event = 0.0
        self._opened_at: dict[int, float] = {}
        self._first_event: dict[int, float] = {}
        """Each window's first event: when it was there, though noticed later."""
        """When each window of the program appeared (bridge time)."""
        self._ever: dict[int, Window] = {}
        """Every window of the program seen, closed ones too (a question answered)."""

    @property
    def trace_path(self) -> Path:
        return self.folder / "trace.jsonl"

    # -- life ------------------------------------------------------------------------------------

    def start(self, timeout: float = 30.0) -> Window:
        if self.bridge is None:
            self.bridge = Bridge(events=True, java_dirs=list(self.options.java_dirs)).start()
        try:
            self.main = self._find_main(timeout)
        except BaseException:
            if self._own_bridge:  # nothing recorded: the bridge is not left running
                self.bridge.close()
                self.bridge = None
            raise
        self.app = program_name(self.main.title)
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "screens").mkdir(exist_ok=True)
        self._t0 = self.bridge.clock()
        header = TraceHeader(
            recording_id=self.folder.name,
            process=self.options.process,
            title=self.options.title,
            note=self.options.note,
            started_at=datetime.now(UTC),
            start_url=screen_url(self.app, None),
            browser=None,
            viewport=(self.main.box[2], self.main.box[3]),
            data=self._keep_data(),
            private=self.options.private,
            program=display_name(self.main.title),
        )
        self.writer = TraceWriter(self.trace_path)
        self.writer.write(header)
        self._windows = {w.hwnd: w for w in self._app_windows()}
        self._depth = {self.main.hwnd: 0}
        self.bridge.events()  # what happened before the start is not the demonstration
        self._last_state = self._capture(self.main.hwnd, self.bridge.clock())
        self._keys = _KeySampler.maybe(self.main.pid)
        return self.main

    def _find_main(self, timeout: float) -> Window:
        assert self.bridge is not None
        end = time.time() + timeout
        while True:
            found = [
                w
                for w in self.bridge.windows(pid=self.options.pid)
                if self.options.window.casefold() in w.title.casefold() and not w.owner
            ]
            if found:
                return max(found, key=lambda w: w.box[2] * w.box[3])
            if time.time() > end:
                raise RuntimeError(
                    f"no Java window with {self.options.window!r} in its title "
                    "(is the program open, and the Java Access Bridge on for it?)"
                )
            time.sleep(0.3)

    def _app_windows(self) -> list[Window]:
        assert self.bridge is not None
        assert self.main is not None
        return list(self.bridge.windows(pid=self.main.pid))

    def _keep_data(self) -> DataRef | None:
        source = self.options.data
        if source is None:
            return None
        import shutil

        target = self.folder / ("data" + source.suffix.lower())
        shutil.copyfile(source, target)
        return DataRef(file=target.name, sheet=self.options.sheet)

    # -- the loop --------------------------------------------------------------------------------

    def _take_events(self) -> list[dict[str, Any]]:
        """The bridge's new events, with the window of each element and the field texts and
        the person's clicks noted."""
        assert self.bridge is not None
        events = self.bridge.events()
        for event in events:
            source = event.get("source")
            t = float(event.get("t") or 0.0)
            if isinstance(source, dict) and "node" in source:
                source["window"] = self._window_of(source)
                hwnd = int(source["window"] or 0)
                self._first_event[hwnd] = min(t, self._first_event.get(hwnd, t))
                if hwnd in self._opened_at:  # it was there before it was noticed
                    self._opened_at[hwnd] = min(self._opened_at[hwnd], t)
                node = source["node"]
                kind = event.get("kind")
                if kind == "text_changed":
                    key = (int(source["window"]), str(node.get("path")))
                    self._texts.setdefault(key, []).append((t, node.get("text")))
                    focus = self.interpreter.focus
                    if focus is not None and focus.key == key:
                        self._human.append(t)  # typing into the field with the focus
                        self._human_windows[t] = hwnd
                elif kind in ("mouse_pressed", "mouse_clicked"):
                    self._human.append(t)
                    self._human_windows[t] = hwnd
            if event.get("kind") not in ("visible_data_changed",):
                self._last_event = max(self._last_event, t)
        return events

    def pump(self) -> int:
        """Turn what happened since the last call into trace events; returns how many."""
        assert self.bridge is not None
        assert self.main is not None
        now = self.bridge.clock()
        # the windows first: an event of a window that just opened is put in it
        windows = {w.hwnd: w for w in self._app_windows()}
        changed = set(windows) != set(self._windows)
        if changed:
            self._windows_opened(windows, now)
            self._last_event = max(self._last_event, now)
        events = self._buffer + self._take_events()
        self._buffer = []
        if changed:
            events.append({"kind": "windows_changed", "t": now})
        if self._keys is not None:
            events += [{"kind": "key", "t": now, "key": k} for k in self._keys.pressed()]
        events.sort(key=lambda e: float(e.get("t") or 0.0))
        if self.options.raw_events and events and not self.options.private:
            import json

            with (self.folder / "bridge-events.jsonl").open("a", encoding="utf-8") as raw:
                for event in events:
                    raw.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        for event in events:
            self.interpreter.feed(event)
        self.interpreter.tick(now)
        for act in self.interpreter.take():
            self._row_of(act)
            self._pending.append((act, self._before(act)))
        settled = self._settle_earlier()
        if not self._pending:
            return settled
        last_act = max(act.t for act, _ in self._pending)
        went_on = next((t for t in self._human if t > last_act + self.HUMAN_GAP), None)
        quiet = now - max(self._last_event, last_act) >= self.options.settle_ms / 1000
        overdue = now - last_act >= self.options.max_settle_ms / 1000
        # a window the action brought up (a question, a message, a list): read it while it is
        # there, before the person answers it (benchmark D01: "Tak" came before the screen
        # after "Zapisz" was read, and the trace never showed the question)
        shown = any(
            opened >= last_act and now - opened >= self.WINDOW_SETTLE
            for hwnd, opened in self._opened_at.items()
            if hwnd in self._windows
        )
        if went_on is None and not quiet and not overdue and not shown:
            return settled
        self._refresh_windows()
        since = min(last_act, self._captured_at) if self._captured_at else last_act
        # A new dialog may already be on top while the bridge has delivered only the
        # next button's press. The preceding action ended on that button's window.
        # Reading the new dialog here would make it the *before* state of its own cause.
        hwnd = self._human_windows.get(went_on) if went_on is not None else None
        if hwnd not in self._windows:
            hwnd = self._front_window(since)
        assert hwnd is not None
        after = self._capture(hwnd, went_on if went_on is not None else now)
        written = settled
        for act, before in self._pending:
            self._write_act(act, before, after)
            written += 1
        self._pending.clear()
        self._last_state = after
        self._human = [t for t in self._human if t > last_act]
        self._human_windows = {t: hwnd for t, hwnd in self._human_windows.items() if t > last_act}
        return written

    def _before(self, act: Act) -> str | None:
        """The screen the act was done on: the last one read, unless that is a window over the
        act's own (a message the act itself brought up, the act told by the bridge only after
        it: benchmark D03 r6, „Przelicz” told after its „Brak ceny” error). A person cannot
        work in a window under a message, so the act came first: its own window is read
        again, as it was just before the act. Only under a message (a window with a title): a
        menu's command is chosen in the menu's own window, which has none, and its screen is
        the one it was chosen on (benchmark D06: File > Save on the price list's frame)."""
        last = self._state_screens.get(self._last_state or "")
        seen = act.seen
        if last is None or seen is None or not seen.window or last.hwnd == seen.window:
            return self._last_state
        if act.menu or seen.window not in self._windows:
            return self._last_state  # a menu's command, or its window is gone
        over = self._windows.get(last.hwnd) or self._ever.get(last.hwnd)
        if over is None or not over.title.strip():
            return self._last_state  # no message over it: a menu, a list, a tooltip
        if self._depth.get(last.hwnd, 0) <= self._depth.get(seen.window, 0):
            return self._last_state  # the act is in the newer window (an answer to a question)
        return self._capture(seen.window, act.t - self.interpreter.press_s) or self._last_state

    def _settle_earlier(self) -> int:
        """Acts the next of which is here already (its press and click came in one batch of
        events): their screen is the one the person saw when the next act began, read now from
        the window the person went on in (benchmark D03: the PO the WZ's row brought, lost when
        Przelicz came in the same batch). Returns how many were written."""
        written = 0
        while len(self._pending) > 1:
            first = self._pending[0][0]
            went_on = next((t for t in self._human if t > first.t + self.HUMAN_GAP), None)
            if went_on is None or went_on > self._pending[-1][0].t:
                break
            group = [entry for entry in self._pending if entry[0].t < went_on]
            rest = self._pending[len(group) :]
            if not group or not rest:
                break
            self._refresh_windows()
            seen = rest[0][0].seen
            hwnd = seen.window if seen is not None and seen.window in self._windows else None
            if hwnd is None:
                since = min(first.t, self._captured_at) if self._captured_at else first.t
                hwnd = self._front_window(since)
            after = self._capture(hwnd, went_on)
            for act, before in group:
                self._write_act(act, before, after)
                written += 1
            self._pending = [(act, after) for act, _ in rest]
            self._last_state = after
        return written

    def _row_of(self, act: Act) -> None:
        """A click in a table: the row it chose, read at once (a list window closes with its
        OK a moment later), and the column clicked (the cell whose text the table said)."""
        seen = act.seen
        if seen is not None and seen.node.path.endswith("/@editor"):
            seen = Seen(
                replace(seen.node, path=seen.node.path.removesuffix("/@editor"), role="table"),
                seen.chain,
                seen.window,
            )
            act.seen = seen
        if seen is None or seen.node.role != "table":
            return
        assert self.bridge is not None
        window = seen.window or self._newest_window()
        try:
            table = self.bridge.table(window, seen.node.path)
        except Exception:
            return
        if table is None:
            return
        # A detached editor may flush after the table lost its selection. The
        # active descendant recorded when editing started identifies its cell.
        index = (
            act.cell_index // len(table.headers)
            if act.type in ("fill", "check", "uncheck")
            and act.cell_index is not None
            and act.cell_index >= 0
            and table.headers
            else table.selected[0]
            if table.selected
            else -1
        )
        if not 0 <= index < len(table.rows):
            return
        cells = dict(zip(table.headers, table.rows[index], strict=False))
        column = (
            table.headers[act.cell_index % len(table.headers)]
            if act.cell_index is not None and act.cell_index >= 0 and table.headers
            else next((h for h, v in cells.items() if act.cell and v == act.cell), None)
        )
        if column is None and act.type in ("check", "uncheck"):
            boxes = []
            for c, header in enumerate(table.headers):
                child = self.bridge.table_cell(window, seen.node.path, index, c)
                if child is not None and child.role == "check box":
                    boxes.append(header)
            if len(boxes) == 1:
                column = boxes[0]
        if column is None:  # no cell named: the first that shows something names the row
            column = next((h for h, v in cells.items() if v.strip()), None)
        act.row = RowContext(table=clean_name(seen.node.name) or None, cells=cells, index=index)
        act.column = column
        act.cell = cells.get(column, act.cell) if column else act.cell

    def _refresh_windows(self) -> None:
        """The program's windows as they are now (benchmark D05: SRK's question opened while
        the main window's screen was being read, half a second, and the screen after
        "Zatwierdź" was taken from the main window instead of the question)."""
        assert self.bridge is not None
        with contextlib.suppress(Exception):
            windows = {w.hwnd: w for w in self._app_windows()}
            if set(windows) != set(self._windows):
                self._windows_opened(windows, self.bridge.clock())

    def _windows_opened(self, windows: dict[int, Window], now: float) -> None:
        for hwnd, window in windows.items():
            self._ever[hwnd] = window
            if hwnd not in self._windows:
                self._opened_at[hwnd] = min(now, self._first_event.get(hwnd, now))
            if hwnd not in self._depth:
                owner_depth = self._depth.get(window.owner, 0) if window.owner else 0
                self._depth[hwnd] = owner_depth + 1 if window.owner else 0
        self._windows = windows

    def _window_of(self, source: dict[str, Any]) -> int:
        """The window an element is in. The bridge sometimes cannot say (a question's button,
        described as the question closes): then the window titled as the dialog around it,
        else the interpreter puts it where it saw the element last."""
        window = int(source.get("window") or 0)
        # the innermost dialog around it, when a window of the program has that title: the
        # bridge maps a question's window only once it was read, and says the main one before
        # (benchmark D05: SRK's question over a frame of the main window)
        for role, name in source.get("chain") or []:
            if role in ("dialog", "window") and name:
                titled = [
                    hwnd
                    for hwnd, known in [*self._windows.items(), *self._ever.items()]
                    if known.title == name and hwnd != window
                ]
                if titled:
                    return titled[0]
                break
        if window in self._windows:
            return window
        for role, name in source.get("chain") or []:
            if role in ("dialog", "frame", "window") and name:
                for hwnd, known in [*self._windows.items(), *self._ever.items()]:
                    if known.title == name:
                        return hwnd
        return 0

    def _newest_window(self) -> int:
        open_ = [h for h in self._windows if h in self._depth]
        if not open_:
            return self.main.hwnd if self.main else 0
        return max(open_, key=lambda h: self._depth[h])

    def _front_window(self, since: float | None = None) -> int:
        """The window the person works in: one that an action since ``since`` opened, else the
        one with the focus, else the newest one."""
        if since is not None:
            opened = [
                h for h, t in self._opened_at.items() if t >= since - 0.1 and h in self._windows
            ]
            if opened:
                return max(opened, key=lambda h: self._opened_at[h])
        focus = self.interpreter.focus
        if focus is not None and focus.window in self._windows:
            return focus.window
        return self._newest_window()

    def record_until(
        self,
        *,
        stop_file: Path | None = None,
        timeout_s: float | None = None,
        stop: Callable[[], bool] | None = None,
        progress: Callable[[int], None] | None = None,
    ) -> Path:
        """Record until the program's main window closes, ``stop_file`` appears, ``stop`` says
        so (a button in Studio) or the time is up; then finish the trace. ``progress`` hears how
        many events are written."""
        end = time.time() + timeout_s if timeout_s else None
        reason = "stopped"
        try:
            while True:
                if self.pump() and progress is not None:
                    progress(self._seq)
                if stop is not None and stop():
                    break
                if stop_file is not None and stop_file.exists():
                    break
                if self.main is not None and self.main.hwnd not in self._windows:
                    reason = "closed"
                    break
                if end is not None and time.time() > end:
                    reason = "timeout"
                    break
                time.sleep(0.05)
        except KeyboardInterrupt:
            reason = "stopped"
        return self.stop(reason)

    def stop(self, reason: str = "stopped") -> Path:
        assert self.writer is not None
        if self.bridge is not None:
            with contextlib.suppress(Exception):
                for _ in range(3):
                    self.pump()
                    time.sleep(0.1)
            now = self.bridge.clock()
            self.interpreter.finish(now)
            for act in self.interpreter.take():
                self._pending.append((act, self._last_state))
            if self._pending:
                if self.main:
                    self._refresh_windows()
                after = self._capture(self._front_window(), now) if self.main else None
                for act, before in self._pending:
                    self._write_act(act, before, after)
                self._pending.clear()
        self.writer.write(
            TraceEnd(
                t=self._time(self.bridge.clock() if self.bridge else self._t0),
                ended_at=datetime.now(UTC),
                reason=reason if reason in ("closed", "stopped", "timeout") else "stopped",
                events=self._seq,
                states=self._states,
            )
        )
        self.writer.close()
        if self._own_bridge and self.bridge is not None:
            self.bridge.close()
        return self.trace_path

    def _time(self, bridge_t: float) -> float:
        return max(0.0, round(bridge_t - self._t0, 3))

    # -- writing ---------------------------------------------------------------------------------

    def _screen(self, hwnd: int) -> Screen | None:
        assert self.bridge is not None
        window = self._windows.get(hwnd)
        if window is None:
            return None
        try:
            nodes = self.bridge.tree(hwnd)
        except Exception:
            return None
        tables = {}
        for node in nodes:
            if node.role == "table" and node.showing:
                with contextlib.suppress(Exception):
                    table = self.bridge.table(hwnd, node.path)
                    if table is not None:
                        tables[node.path] = table
        screen = build_screen(window.title, hwnd, nodes, tables=tables)
        self._screens[hwnd] = screen
        self._last_screen = screen
        return screen

    def _capture(self, hwnd: int, until: float) -> str | None:
        """The window's screen as it was at ``until`` (bridge time)."""
        assert self.writer is not None
        assert self.bridge is not None
        screen = self._screen(hwnd)
        if screen is None:
            return self._last_state
        self.interpreter.status_labels |= status_labels(screen)
        read = self.bridge.clock()  # a big screen takes a while: the person may type meanwhile
        self._drain()  # typing while the screen was read
        reverted = self._as_at(screen, hwnd, until)
        # what the fields held, as of the end of the read: a field typed into while it was being
        # read does not say what it held before (its typing came later than the read asked)
        self.interpreter.remember(
            hwnd,
            {
                e.path: e.value
                for e in screen.elements
                if e.role in ("textbox", "combobox", "spinbutton")
            },
            max(until, read),
        )
        self._states += 1
        self._captured_at = until
        state_id = f"s{self._states:03d}"
        self._state_screens[state_id] = screen
        for old in list(self._state_screens)[:-40]:  # the recent ones are enough
            del self._state_screens[old]
        shot = None
        shot_t = None
        origin = None
        scale = None
        if self.options.screenshots and not self.options.private:
            taken = _screenshot(hwnd, self.folder / "screens" / f"{state_id}.png")
            if taken is not None:
                shot, origin, size, inset = taken
                if screen.nodes:
                    origin, scale = picture_place(screen.nodes[0].box, origin, size)
                per = scale or 1.0  # the picture starts inside the invisible left and top borders
                origin = (round(origin[0] + inset[0] / per), round(origin[1] + inset[1] / per))
                if reverted:  # the picture shows the typing that came later
                    shot_t = self._time(self.bridge.clock())
        window = self._windows.get(hwnd)
        self.writer.write(
            TraceState(
                id=state_id,
                t=self._time(until),
                url=screen_url(self.app, screen.active_frame() or self._dialog_title(window)),
                title=window.title if window else screen.title,
                aria=screen.aria(titles=title_template),
                screenshot=f"screens/{state_id}.png" if shot else None,
                screenshot_t=shot_t,
                window=self._depth.get(hwnd, 0),
                origin=origin,
                scale=scale,
            )
        )
        return state_id

    def _drain(self, *, quiet_s: float = 0.06, max_s: float = 0.5) -> None:
        """The events of what happened while a screen was read: the bridge tells them only
        once it is free again, stamped with that later time (benchmark D06: a price typed
        while 85 fields were read). Taken until the bridge has been quiet a moment."""
        end = time.time() + max_s
        quiet_since = time.time()
        while time.time() < end:
            taken = self._take_events()
            if taken:
                self._buffer.extend(taken)
                quiet_since = time.time()
            elif time.time() - quiet_since >= quiet_s:
                return
            time.sleep(0.02)

    def _as_at(self, screen: Screen, hwnd: int, until: float) -> bool:
        """Fields changed after ``until`` show what they held at it (the screen after an Enter
        is not the one with the next field already typed); whether any did."""
        changed = False
        for element in screen.elements:
            if element.role not in ("textbox", "spinbutton"):
                continue
            history = self._texts.get((hwnd, element.path))
            if not history or history[-1][0] <= until:
                continue
            earlier = [text for t, text in history if t <= until]
            if earlier:
                element.value = earlier[-1]
            else:
                known = self.interpreter.known.get((hwnd, element.path))
                element.value = known[1] if known is not None and known[0] <= until else ""
            changed = True
        if changed:  # a block's rows as they were then too (benchmark D06: the new line's
            fill_block_cells(screen.elements)  # Product Value was empty before it was typed)
        return changed

    def _dialog_title(self, window: Window | None) -> str | None:
        if window is None or self.main is None or window.hwnd == self.main.hwnd:
            return None
        return window.title

    def _write_act(self, act: Act, before: str | None, after: str | None) -> None:
        assert self.writer is not None
        seen = act.seen
        target = None
        url = None
        title = None
        window_depth = 0
        if seen is not None:
            screen = self._screens.get(seen.window)
            earlier = self._state_screens.get(before or "")
            if (
                earlier is not None
                and earlier.hwnd == seen.window
                and earlier.by_path(seen.node.path) is not None
            ):
                screen = earlier  # its row as it was before the act
            toolbar = _toolbar_index(screen, seen.node) if screen is not None else None
            target = element_info(seen, screen, toolbar_index=toolbar)
            if target.bbox is None and earlier is not None:
                # its window closed as it was clicked („Tak” in a question): the bridge tells
                # neither its place nor its whole path; the screen read before has the one
                # element of that role and name
                kind = (seen.node.role, seen.node.name)
                alike = [
                    e
                    for e in earlier.elements
                    if (e.node.role, e.node.name) == kind and _placed(e.node.box)
                ]
                if len(alike) == 1:
                    target = target.model_copy(update={"bbox": alike[0].node.box})
            if act.row is not None:  # a row of a table: its cell, in its row
                cell = (act.column if act.type in ("check", "uncheck", "fill") else act.cell) or ""
                target = target.model_copy(
                    update={
                        "tag": "java:table cell",
                        "role": "cell",
                        "name": cell or None,
                        "text": cell or None,
                        "label": act.column if act.type == "fill" else None,
                        "column": act.column,
                        "row": act.row,
                        "candidates": [Locator(role="cell", column=act.column)]
                        if act.column
                        else [],
                    }
                )
            if act.menu and target.name:
                target = target.model_copy(
                    update={
                        "text": f"{act.menu} > {target.name}",
                        "column": act.menu,
                        "candidates": [
                            Locator(role="menuitem", name=target.name, column=act.menu),
                            *target.candidates,
                        ],
                    }
                )
            if not seen.window:
                seen = Seen(seen.node, seen.chain, self._newest_window())
            window = self._windows.get(seen.window) or self._ever.get(seen.window)
            title = window.title if window else None
            frame = seen.frame or self._dialog_title(window)
            if frame is None and act.menu and screen is not None:
                # a menu's command works on the frame the person worked in (File > Save saves
                # the form they typed in, Close Form closes it): its step is on that screen,
                # while that frame is open on the screen before it (benchmark D06)
                then = earlier if earlier is not None and earlier.hwnd == seen.window else screen
                open_frames = {title for title, _ in then.frames}
                worked = self._worked_in if self._worked_in in open_frames else None
                frame = worked or then.active_frame()
            elif seen.frame is not None and self.main is not None and seen.window == self.main.hwnd:
                self._worked_in = seen.frame
            url = screen_url(self.app, frame)
            window_depth = self._depth.get(seen.window, 0)
        self._seq += 1
        self.writer.write(
            TraceEvent(
                seq=self._seq,
                t=self._time(act.t),
                type=act.type,
                url=url,
                title=title,
                target=target,
                value=None if act.secret else act.value,
                option_label=act.option_label,
                secret=act.secret,
                window=window_depth,
                state_before=before,
                state_after=after,
            )
        )


def _toolbar_index(screen: Screen, node: Node) -> int | None:
    if node.name.strip():
        return None
    bars = [n for n in screen.nodes if n.role == "tool bar"]
    for bar in bars:
        if node.is_under(bar):
            buttons = [n for n in screen.nodes if n.is_under(bar) and n.role == "push button"]
            for index, button in enumerate(buttons, start=1):
                if button.path == node.path:
                    return index
    return None


def picture_place(
    window: tuple[int, int, int, int], corner: tuple[int, int], size: tuple[int, int]
) -> tuple[tuple[int, int], float | None]:
    """Where a window's picture starts among the places the bridge tells, and how many of the
    picture's pixels make one of theirs (None: one). ``window`` is the window's place as the
    bridge tells it; ``corner`` and ``size`` the picture's, as Windows tells them. The picture is
    taken in the window's own pixels, so the two agree; should they not (a display scaled to
    125 % read in other pixels than the program's: the clean-Windows Lite test of 12.10 framed
    the field below the one typed into), the marks are drawn where the bridge says."""
    width = window[2]
    if width <= 0 or size[0] <= 0:
        return corner, None
    scale = size[0] / width
    if abs(scale - 1) < 0.03:  # the same pixels: a frame's border or two is no scaling
        return corner, None
    return (window[0], window[1]), round(scale, 4)


def visible_inset(
    window: tuple[int, int, int, int], frame: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """How far a window's visible frame lies inside its rectangle: left, top, right, bottom.
    Both are (left, top, right, bottom) on the screen. Windows 10 and 11 count invisible
    resize borders into a window's rectangle, and its picture shows them black (the
    clean-Windows Lite test of 12.10: black bars left, right and below SRK's question at
    125 %). Nothing is left out unless the frame is a few pixels inside the rectangle: DWM
    tells the screen's pixels, and a program that does not know the display is scaled has
    its rectangle in other ones."""
    inset = (frame[0] - window[0], frame[1] - window[1], window[2] - frame[2], window[3] - frame[3])
    if frame[2] > frame[0] and frame[3] > frame[1] and all(0 <= side <= 40 for side in inset):
        return inset
    return (0, 0, 0, 0)


def _screenshot(
    hwnd: int, path: Path
) -> tuple[Path, tuple[int, int], tuple[int, int], tuple[int, int, int, int]] | None:
    """The window as it is now (PrintWindow: it works off screen and on another desktop), where
    its top left corner is on the screen (the bridge tells elements' places on it) and its
    size, all in the window's own pixels, and how much of its edges the picture leaves out
    (``visible_inset``: the invisible borders)."""
    try:
        from PIL import Image

        user32 = getattr(__import__("ctypes"), "WinDLL")("user32")  # noqa: B009
        gdi32 = getattr(__import__("ctypes"), "WinDLL")("gdi32")  # noqa: B009
        import ctypes

        class _R(ctypes.Structure):
            _fields_ = [
                ("l", ctypes.c_long),
                ("t", ctypes.c_long),
                ("r", ctypes.c_long),
                ("b", ctypes.c_long),
            ]

        user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_R)]
        user32.GetWindowDC.argtypes = [ctypes.c_void_p]
        user32.GetWindowDC.restype = ctypes.c_void_p
        user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
        gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
        gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
        gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi32.GetDIBits.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
        # In the window's own pixels: on a display scaled to 125 % a program that knows it (Java
        # 9 and later) is drawn, and told by the bridge, in the screen's pixels, one that does
        # not (Java 8) in the scaled ones. Read in this process's, the window of the first was
        # cut to four fifths (the clean-Windows Lite test of 12.10: „Zapisz” off its picture).
        own = getattr(user32, "GetWindowDpiAwarenessContext", None)
        use = getattr(user32, "SetThreadDpiAwarenessContext", None)
        before = None
        if own is not None and use is not None:
            own.argtypes, own.restype = [ctypes.c_void_p], ctypes.c_void_p
            use.argtypes, use.restype = [ctypes.c_void_p], ctypes.c_void_p
            context = own(hwnd)
            before = use(context) if context else None
        try:
            rect = _R()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w, h = rect.r - rect.l, rect.b - rect.t
            if w <= 0 or h <= 0:
                return None
            wdc = user32.GetWindowDC(hwnd)
            mdc = gdi32.CreateCompatibleDC(wdc)
            bmp = gdi32.CreateCompatibleBitmap(wdc, w, h)
            gdi32.SelectObject(mdc, bmp)
            user32.PrintWindow(hwnd, mdc, 2)
            header = (ctypes.c_uint32 * 10)(
                40, w, (-h) & 0xFFFFFFFF, 1 | (32 << 16), 0, 0, 0, 0, 0, 0
            )
            buf = ctypes.create_string_buffer(w * h * 4)
            gdi32.GetDIBits(mdc, bmp, 0, h, buf, header, 0)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mdc)
            user32.ReleaseDC(hwnd, wdc)
            inset = (0, 0, 0, 0)
            try:  # the frame as DWM draws it; none where nothing composes (another desktop)
                dwmapi = getattr(ctypes, "WinDLL")("dwmapi")  # noqa: B009
                dwmapi.DwmGetWindowAttribute.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_uint,
                    ctypes.c_void_p,
                    ctypes.c_uint,
                ]
                dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
                frame = _R()
                extended_frame_bounds = 9
                told = dwmapi.DwmGetWindowAttribute(
                    hwnd, extended_frame_bounds, ctypes.byref(frame), ctypes.sizeof(frame)
                )
                if told == 0:
                    window = (rect.l, rect.t, rect.r, rect.b)
                    inset = visible_inset(window, (frame.l, frame.t, frame.r, frame.b))
            except Exception:
                inset = (0, 0, 0, 0)
        finally:
            if before and use is not None:
                use(before)
        path.parent.mkdir(parents=True, exist_ok=True)
        picture = Image.frombuffer("RGB", (w, h), bytes(buf.raw), "raw", "BGRX", 0, 1)
        if any(inset):
            picture = picture.crop((inset[0], inset[1], w - inset[2], h - inset[3]))
        picture.save(path)
        return path, (rect.l, rect.t), (w, h), inset
    except Exception:
        return None


class _KeySampler:
    """Navigation keys as the person presses them (Enter, Escape, Tab, arrows, F keys), read
    from the keyboard's state; letters are never read. Only where Maptelo shares the desktop
    with the person: on another desktop (the benchmark's) it stays empty."""

    KEYS: ClassVar[dict[int, str]] = {
        0x0D: "Enter",
        0x1B: "Escape",
        0x09: "Tab",
        0x28: "ArrowDown",
        0x26: "ArrowUp",
        0x22: "PageDown",
        0x7A: "F11",
    }

    def __init__(self, user32: Any, pid: int) -> None:
        self.user32 = user32
        self.pid = pid
        self.down: set[int] = set()

    @classmethod
    def maybe(cls, pid: int) -> _KeySampler | None:
        import ctypes

        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:
            return None
        user32 = loader("user32")
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        if not user32.GetForegroundWindow():
            return None  # not the desktop the person works on
        return cls(user32, pid)

    def _in_program(self) -> bool:
        """Keys count only while the recorded program is the window in front: what the
        person types into another program is none of the recording's business."""
        import ctypes

        pid = ctypes.c_ulong()
        self.user32.GetWindowThreadProcessId(self.user32.GetForegroundWindow(), ctypes.byref(pid))
        return pid.value == self.pid

    def pressed(self) -> list[str]:
        if not self._in_program():
            self.down.clear()
            return []
        out = []
        shift = bool(self.user32.GetAsyncKeyState(0x10) & 0x8000)
        ctrl = bool(self.user32.GetAsyncKeyState(0x11) & 0x8000)
        for vk, name in self.KEYS.items():
            down = bool(self.user32.GetAsyncKeyState(vk) & 0x8000)
            if down and vk not in self.down:
                if name == "Tab" and shift:
                    name = "Shift+Tab"
                if name == "F11" and ctrl:
                    name = "Ctrl+F11"
                out.append(name)
            if down:
                self.down.add(vk)
            else:
                self.down.discard(vk)
        return out


def record_java_session(
    folder: Path,
    options: JavaRecorderOptions,
    *,
    stop_file: Path | None = None,
    timeout_s: float | None = None,
) -> Path:
    """Record a demonstration in a Java program until its window closes, ``stop_file``
    appears, the time is up, or Ctrl+C."""
    recorder = JavaRecorder(folder, options)
    recorder.start()
    return recorder.record_until(stop_file=stop_file, timeout_s=timeout_s)
