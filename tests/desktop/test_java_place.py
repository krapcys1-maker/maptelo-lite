"""A field or a box is known by where it stands on the screen, not by its path.

Oracle Forms puts its list-of-values button "…" first among the canvas's children, by the field
with the focus, a server's answer after the focus came, and takes it away when the focus leaves.
Every element after it then has another path: the focus, the typing and the screens read around
them named three different fields (each value written under the next field, typed values
said to be the program's, „EU” for „EUR”). Reproduced on a Swing form built that way: the
events below are its bridge's, made shorter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from maptelo.capture.java import (
    Interpreter,
    JavaRecorder,
    JavaRecorderOptions,
    Seen,
    element_at,
    element_info,
)
from maptelo.desktop.jab import Node
from maptelo.desktop.screen import build_screen

STATES = ["enabled", "showing", "visible", "focusable", "editable"]
DIALOG = [("dialog", "Additional Price List Information"), ("frame", "Oracle Applications")]
REBATE = (468, 271, 80, 22)
ACCRUAL = (468, 301, 80, 22)
REGION = (468, 331, 80, 22)


def ev(
    kind: str,
    t: float,
    name: str,
    path: str,
    box: tuple[int, int, int, int],
    *,
    role: str = "text",
    text: str | None = None,
    window: int = 1,
    **extra: Any,
) -> dict[str, Any]:
    node: dict[str, Any] = {"path": path, "role": role, "name": name, "states": STATES}
    node["box"] = list(box)
    if text is not None:
        node["text"] = text
    return {
        "kind": kind,
        "t": t,
        "source": {"node": node, "chain": DIALOG, "window": window},
        **extra,
    }


def test_typing_is_the_fields_own_when_the_list_button_came_before_it_meanwhile() -> None:
    """„Rebate” got the focus at 0/0/0; its „…” came first among the canvas's children 150 ms
    later, and the typing was told at 0/0/1. It was the person's typing all the same (the map
    said the program wrote it, and lost the value)."""
    it = Interpreter()
    it.feed(ev("focus", 13.212, "Rebate List of Values", "0/0/0", REBATE, text=""))
    it.feed(ev("text_changed", 14.198, "Rebate List of Values", "0/0/1", REBATE, text="YES"))
    it.feed(ev("focus", 14.504, "Accrual List of Values", "0/0/2", ACCRUAL, text=""))
    it.feed(ev("text_changed", 15.004, "Accrual List of Values", "0/0/2", ACCRUAL, text="YES"))
    it.feed(ev("focus", 15.309, "Region List of Values", "0/0/3", REGION, text=""))
    it.feed(ev("text_changed", 15.809, "Region List of Values", "0/0/3", REGION, text="EUR"))
    it.finish(16.0)
    acts = it.take()
    assert [(a.type, a.value, a.seen.node.name if a.seen else None) for a in acts] == [
        ("fill", "YES", "Rebate List of Values"),
        ("fill", "YES", "Accrual List of Values"),
        ("fill", "EUR", "Region List of Values"),
    ]


def test_the_program_writing_the_field_now_at_the_focused_fields_old_path_is_not_typing() -> None:
    """„Name” had the focus at 0/0/1 (its „…” first); the button went, and the program wrote
    -1 into „Grouping Number”, at 0/0/1 now. The same path, another field: not the typing of
    the field with the focus (the map had the person type -1)."""
    name, grouping = (212, 160, 200, 22), (212, 280, 60, 22)
    it = Interpreter()
    it.feed(ev("focus", 1.0, "Name", "0/0/1", name, text=""))
    it.feed(ev("text_changed", 2.0, "Grouping Number", "0/0/1", grouping, text="-1"))
    it.feed(ev("focus", 3.0, "Currency", "0/0/2", (212, 190, 80, 22), text=""))
    it.finish(4.0)
    assert [a.type for a in it.take()] == []


def test_a_field_told_without_a_place_is_known_by_where_its_path_last_stood() -> None:
    """The last letter of „EUR” told as the window closed (OK pressed at once): the bridge has
    no place for the field then. It is still the field the person typed into."""
    it = Interpreter()
    it.feed(ev("focus", 1.0, "Region List of Values", "0/0/3", REGION, text=""))
    it.feed(ev("text_changed", 1.2, "Region List of Values", "0/0/3", REGION, text="EU"))
    gone = (-1, -1, -1, -1)
    it.feed(ev("text_changed", 1.3, "Region List of Values", "0/0/3", gone, text="EUR"))
    it.finish(2.0)
    assert [(a.type, a.value) for a in it.take()] == [("fill", "EUR")]


def test_a_value_the_screen_showed_at_the_fields_place_is_not_typed_again() -> None:
    """A screen read with the button by another field: „Currency” at another path then. The
    value it showed there is what the field held before the focus came."""
    currency = (212, 190, 80, 22)
    it = Interpreter()
    place = it.place_of(1, Node("0/0/1", "text", "Currency", box=currency))
    it.remember(1, {place: "USD"}, 0.5)
    it.feed(ev("focus", 1.0, "Currency", "0/0/2", currency, text="USD"))
    it.feed(ev("text_changed", 1.4, "Currency", "0/0/2", currency, text="USD"))
    it.feed(ev("focus", 2.0, "Start Date", "0/0/3", (212, 220, 110, 22), text=""))
    it.finish(3.0)
    assert [a.type for a in it.take()] == []


def _canvas(*fields: tuple[str, str, tuple[int, int, int, int]]) -> list[Node]:
    shown = frozenset(STATES)
    nodes = [Node("0", "frame", "Oracle Applications", states=shown, box=(0, 0, 900, 560))]
    return nodes + [Node(path, "text", name, states=shown, box=box) for path, name, box in fields]


START = (212, 220, 110, 22)
END = (342, 220, 110, 22)


def test_a_field_is_named_by_the_screens_field_at_its_place_not_at_its_path() -> None:
    """A date typed into „Start Date” while its „…” stood first on the canvas: its path then is
    the one „End Date” had on the screen read before, without the button. The step is „Start
    Date” (the map wrote the date under „End Date”)."""
    before = build_screen(
        "Oracle Applications",
        1,
        _canvas(("0/2", "Start Date", START), ("0/3", "End Date", END)),
    )
    typed = Node("0/3", "text", "Start Date", box=START, text="01-NOV-2026")
    assert element_at(before, typed) is not None
    assert element_at(before, typed).name == "Start Date"  # type: ignore[union-attr]
    info = element_info(Seen(typed, [], 1), before)
    assert (info.name, info.label, info.bbox) == ("Start Date", "Start Date", START)
    # the field where its path says, when no element of its kind stands at its place (the
    # window moved): the path is all there is
    moved = Node("0/3", "text", "End Date", box=(400, 300, 110, 22))
    assert element_at(before, moved).name == "End Date"  # type: ignore[union-attr]


def test_a_screen_shows_each_field_as_it_was_by_its_own_typing(tmp_path: Path) -> None:
    """A screen read after „EUR” was typed, of the moment before: „Region” shows „EU”, and the
    field at the path the typing was told at (another one, the button gone meanwhile) keeps
    its own value (the map had the program write „EU” into the next field)."""
    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    screen = build_screen(
        "Additional Price List Information",
        1,
        _canvas(("0/1", "Accrual", ACCRUAL), ("0/2", "Region", REGION)),
    )
    screen.elements[0].value, screen.elements[1].value = "YES", "EUR"
    told = Node("0/1", "text", "Region", box=REGION)  # told with the button first
    key = (1, rec.interpreter.place_of(1, told))
    rec._texts[key] = [(1.0, "E"), (1.1, "EU"), (2.0, "EUR")]
    assert rec._as_at(screen, 1, 1.5)
    assert [(e.name, e.value) for e in screen.elements] == [("Accrual", "YES"), ("Region", "EU")]


def test_a_name_that_carries_the_fields_value_is_still_that_field() -> None:
    """Oracle Forms names a field with a list „<prompt> List Values: <its value>”: the name
    changes with every letter typed. The field is the same, and named by its prompt."""
    box = (212, 400, 80, 22)
    it = Interpreter()
    it.feed(ev("focus", 1.0, "Main tab page Export Control List Values: ", "0/0/9", box, text=""))
    it.feed(ev("text_changed", 1.2, "Main tab page Export Control List Values: Y", "0/0/9", box,
               text="Y"))  # fmt: skip
    it.feed(ev("text_changed", 1.4, "Main tab page Export Control List Values: Yes", "0/0/9", box,
               text="Yes"))  # fmt: skip
    it.feed(ev("focus", 2.0, "Region List of Values", "0/0/10", REGION, text=""))
    acts = it.take()
    assert [(a.type, a.value) for a in acts] == [("fill", "Yes")]
    screen = build_screen("Oracle Applications", 1, _canvas(("0/0/9", "Export Control", box)))
    seen = acts[0].seen
    assert seen is not None
    assert element_info(seen, screen).name == "Export Control"
    assert element_info(seen, None).name == "Export Control"


def test_a_row_of_a_list_told_at_the_path_of_a_button_is_that_row() -> None:
    """The list of values' frame came first in the window after the screen was read: the row
    the person clicked is told at the path the field's „…” had on that screen. The step is the
    row („31830-D / …”), not „the … by Product Value” (benchmark D08: the first item's pick was
    lost, and the map asked who decides to click „…”)."""
    shown = frozenset(STATES)
    row = "31830-D / 698661121 / Firma Testowa sp. z o.o."
    before = build_screen(
        "Oracle Applications",
        1,
        [
            Node("0", "frame", "Oracle Applications", states=shown, box=(0, 0, 900, 560)),
            Node("0/0", "push button", "", states=shown, box=(300, 100, 22, 20)),
            Node("0/1", "text", "Product Value", states=shown, box=(170, 100, 125, 20)),
        ],
    )
    label = Node("0/0", "label", row, states=shown)  # a row the list told, without a place
    info = element_info(Seen(label, [("internal frame", "Customer Items")], 1), before)
    assert (info.role, info.name) == ("option", row)
    assert info.beside is None


def test_a_label_that_is_text_on_the_screen_stays_text() -> None:
    shown = frozenset(STATES)
    before = build_screen(
        "Oracle Applications",
        1,
        [
            Node("0", "frame", "Oracle Applications", states=shown, box=(0, 0, 900, 560)),
            Node("0/0", "label", "Record: 1/1", states=shown, box=(10, 540, 80, 18)),
        ],
    )
    label = Node("0/0", "label", "Record: 1/1", states=shown)
    assert element_info(Seen(label, [], 1), before).role == "text"
