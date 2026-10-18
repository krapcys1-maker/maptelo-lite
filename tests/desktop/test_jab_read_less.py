"""The bridge asks Java only what a recording uses: every question is a turn of the program's
event thread, and a screen rebuilt is told as a burst of events (WCR's calendar: 82 for its
next month; Oracle Forms tells far more). An element whose event only says the program still
reacts is not placed in its window, one whose event says nothing used is not read at all, and
an element placed is placed in one climb."""

from types import SimpleNamespace
from typing import Any

import pytest

from maptelo.desktop.jab import Bridge, Node


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> tuple[Bridge, dict[str, Any], list[str]]:
    bridge = Bridge(events=True)
    callbacks: dict[str, Any] = {}
    asked: list[str] = []
    dll = SimpleNamespace()
    for name in (
        "setFocusGainedFP",
        "setPropertyStateChangeFP",
        "setPropertyChildChangeFP",
        "setPropertyNameChangeFP",
        "setPropertyValueChangeFP",
    ):

        def register(callback: Any, name: str = name) -> None:
            callbacks[name] = callback

        setattr(dll, name, register)
    bridge._d = dll
    bridge._subscribe()
    roles = {21: "push button", 22: "check box", 23: "page tab", 24: "list item", 25: "table"}

    def info(vm: int, obj: int) -> Any:
        asked.append(f"info {obj}")
        return SimpleNamespace(
            role_en_US=roles.get(obj, "panel"),
            role="",
            name=f"e{obj}",
            indexInParent=0,
            states_en_US="enabled,showing",
            states="",
        )

    def place(vm: int, obj: int) -> Any:
        asked.append(f"place {obj}")
        return "0/1", 41, [("dialog", "Kalendarz")], None

    def node(vm: int, obj: int, path: str, **kwargs: Any) -> Node:
        asked.append(f"node {obj} actions={kwargs.get('actions', True)}")
        return Node(path, roles.get(obj, "panel"), f"e{obj}")

    monkeypatch.setattr(bridge, "_info", info)
    monkeypatch.setattr(bridge, "_place", place)
    monkeypatch.setattr(bridge, "_node", node)
    monkeypatch.setattr(bridge, "_release", lambda vm, *objects: None)
    monkeypatch.setattr(bridge, "clock", lambda: 1.0)
    return bridge, callbacks, asked


def test_events_saying_only_that_the_screen_changes_are_not_placed(bridge) -> None:
    b, callbacks, asked = bridge
    callbacks["setPropertyStateChangeFP"](1, 11, 21, "(null)", "focused")
    callbacks["setPropertyNameChangeFP"](1, 12, 21, "Październik", "Listopad")
    callbacks["setPropertyValueChangeFP"](1, 13, 21, "10", "11")
    callbacks["setPropertyChildChangeFP"](1, 14, 30, 31, 32)  # a panel's buttons replaced
    b._read_pending_events()
    told = b.events()
    assert [e["kind"] for e in told] == [
        "state_changed",
        "name_changed",
        "value_changed",
        "child_changed",
    ]
    assert [e["source"] for e in told[:3]] == [None, None, None]  # not read at all
    assert told[3]["source"] == {"node": {"role": "panel", "name": "e30"}}
    assert told[3]["new"]["name"] == "e32"  # a frame or a table's cell coming is still told
    assert told[0]["new"] == "focused"
    assert asked == ["info 30", "info 31", "info 32"]  # its role, then the old and new child


def test_a_box_ticked_a_tab_chosen_and_a_table_changed_are_placed(bridge) -> None:
    b, callbacks, asked = bridge
    callbacks["setPropertyStateChangeFP"](1, 11, 22, "(null)", "checked")
    callbacks["setPropertyStateChangeFP"](1, 12, 23, "(null)", "selected")
    callbacks["setPropertyStateChangeFP"](1, 13, 24, "(null)", "selected")  # a list's row
    callbacks["setPropertyChildChangeFP"](1, 14, 25, 0, 33)  # a table's cell editor
    b._read_pending_events()
    told = b.events()
    placed = [e["source"]["window"] for e in told if e["source"] and "window" in e["source"]]
    assert placed == [41, 41, 41]
    assert told[2]["source"] == {"node": {"role": "list item", "name": "e24"}}
    assert "place 24" not in asked


def test_what_a_person_did_is_placed_without_what_the_element_can_do(bridge) -> None:
    b, callbacks, asked = bridge
    callbacks["setFocusGainedFP"](1, 11, 21)
    b._read_pending_events()
    (focus,) = b.events()
    assert focus["source"]["chain"] == [("dialog", "Kalendarz")]
    assert asked == ["place 21", "node 21 actions=False"]


PARENTS = {1: 2, 2: 3, 3: 4, 4: 0}
"""A dialog's button: button -> panel (a root pane says -1) -> dialog (a top-level window) -> its
owner frame, as the bridge gives parents."""
INFOS = {
    1: ("push button", "Następny miesiąc", 3),
    2: ("panel", "", -1),
    3: ("dialog", "Kalendarz", 0),
    4: ("frame", "WCR", 0),
}


def climb_dll(asked: list[str]) -> SimpleNamespace:
    def hwnd(vm: int, obj: int) -> int:
        asked.append("hwnd")
        return 300 if obj == 3 else 400 if obj == 4 else 0

    def parent(vm: int, obj: int) -> int:
        asked.append("parent")
        return PARENTS[obj]

    def child(vm: int, obj: int, i: int) -> int:
        asked.append("child")
        return 22 if (obj, i) == (3, 1) else 9  # a new reference to the panel, or another

    def same(vm: int, a: int, b: int) -> int:
        asked.append("same")
        return int({a, b} == {2, 22})

    return SimpleNamespace(
        getHWNDFromAccessibleContext=hwnd,
        getAccessibleParentFromContext=parent,
        getAccessibleChildFromContext=child,
        isSameObject=same,
    )


def test_an_element_is_placed_in_one_climb(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = Bridge()
    asked: list[str] = []
    bridge._d = climb_dll(asked)
    released: list[int] = []

    def info(vm: int, obj: int) -> Any:
        asked.append("info")
        role, name, index = INFOS[obj]
        return SimpleNamespace(
            role_en_US=role, role="", name=name, indexInParent=index, childrenCount=2
        )

    monkeypatch.setattr(bridge, "_info", info)
    monkeypatch.setattr(bridge, "_top_level", lambda handle: handle in (300, 400))
    monkeypatch.setattr(bridge, "_release", lambda vm, *objects: released.extend(objects))
    path, window, chain, own = bridge._place(1, 1)
    assert (path, window) == ("0/1/3", 300)  # the root pane found among its dialog's children
    assert chain == [("dialog", "Kalendarz"), ("frame", "WCR")]  # the owner above the dialog
    assert own is not None
    assert own.name == "Następny miesiąc"
    assert asked.count("hwnd") == 3  # not asked again above the window it is in
    assert asked.count("info") == 5  # each element once (+ the panel's parent's children)
    assert sorted(released) == [2, 3, 4, 9, 22]  # every reference given back


def test_events_are_taken_between_the_questions_of_a_long_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While the bridge's thread reads a screen, Java's events keep coming: they are taken
    between the questions, so each is stamped near when it came, not all at the read's end."""
    import threading

    bridge = Bridge()
    bridge._thread = threading.current_thread()  # the read runs on the bridge's own thread
    bridge._msg = SimpleNamespace()  # type: ignore[assignment]
    taken: list[int] = []
    children = {1: [2, 3], 2: [], 3: []}
    monkeypatch.setattr(bridge, "_take_messages", lambda limit: taken.append(limit) or True)
    monkeypatch.setattr(bridge, "_root", lambda hwnd: (1, 1))
    monkeypatch.setattr(bridge, "_release", lambda vm, *objects: None)
    monkeypatch.setattr(
        bridge,
        "_node",
        lambda vm, obj, path, **kwargs: Node(
            path, "panel", f"e{obj}", states=frozenset({"showing"}), children=len(children[obj])
        ),
    )
    bridge._d = SimpleNamespace(getAccessibleChildFromContext=lambda vm, obj, i: children[obj][i])
    nodes = bridge.tree(7)
    assert [n.path for n in nodes] == ["0", "0/0", "0/1"]
    assert len(taken) == 3  # before each element's questions


def test_events_that_come_together_keep_their_order_in_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Taken after a read, a field's text and the screen's answer to it come in one batch: each
    is later than the one before by a millisecond, so "the screen reacted after the typing"
    (an Enter) stays true (benchmark M4: both stamped 3.224, the Enter never told)."""
    bridge = Bridge()
    monkeypatch.setattr(bridge, "clock", lambda: 3.224)
    assert [bridge._stamp() for _ in range(3)] == [3.224, 3.225, 3.226]
    monkeypatch.setattr(bridge, "clock", lambda: 3.5)
    assert bridge._stamp() == 3.5  # later events keep their own time
