"""Oracle Forms puts its list-of-values button "…" (a push button without a name) beside the field
the focus came to, a server's answer later, and takes it away from the field the focus left. It
came just after the typing of a field gone through with Tab: the recording had an Enter after
every such field (benchmark D09). A screen answering the typing is still an Enter."""

from __future__ import annotations

from typing import Any

from maptelo.capture.java import Interpreter

STATES = ["enabled", "showing", "visible", "focusable", "editable"]
CHAIN = [("internal frame", "Sales Orders"), ("frame", "Wiorek Applications")]
QTY = (1158, 648, 59, 20)
BUTTON = {"role": "push button", "name": "", "index": -1, "states": ["enabled", "visible"]}


def ev(kind: str, t: float, **extra: Any) -> dict[str, Any]:
    node = {"path": "0/0/91", "role": "text", "name": "Qty Required", "states": STATES}
    node["box"] = list(QTY)
    node["text"] = "55"
    return {"kind": kind, "t": t, "source": {"node": node, "chain": CHAIN, "window": 1}, **extra}


def _typed(it: Interpreter) -> None:
    it.feed(ev("focus", 10.0))
    it.feed(ev("text_changed", 10.05))


def test_the_list_button_coming_or_going_is_no_enter() -> None:
    for old, new in ((BUTTON, None), (None, BUTTON)):
        it = Interpreter()
        _typed(it)
        pane = {"node": {"role": "layered pane", "name": ""}}
        it.feed({"kind": "child_changed", "t": 10.2, "source": pane, "old": old, "new": new})
        it.tick(11.0)
        it.finish(11.5)
        assert [a.type for a in it.take()] == ["fill"]


def test_a_screen_answering_the_typing_is_still_an_enter() -> None:
    it = Interpreter()
    _typed(it)
    total = {"node": {"role": "layered pane", "name": ""}}
    row = {"role": "label", "name": "Line Total", "index": 3, "states": ["visible"]}
    it.feed({"kind": "child_changed", "t": 10.2, "source": total, "old": None, "new": row})
    it.tick(11.0)
    assert [(a.type, a.value) for a in it.take()] == [("fill", "55"), ("press", "Enter")]
