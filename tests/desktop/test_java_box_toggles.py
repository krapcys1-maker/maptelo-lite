"""A box clicked: its press, the state it gave and its click are one act; the same box ticked
and unticked in turn is one step, its last state.

„Active” unticked, ticked and clicked were three steps. Swing ticks a box at the release, so
the bridge tells its state between the press and the click; a box that did not have the focus
was told only as a click (its state lost), one that had it as the state and a click."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from maptelo.capture.java import Interpreter
from maptelo.mapping import normalize
from maptelo.trace import ElementInfo, Trace, TraceEvent, TraceHeader

FORM = [("internal frame", "Price Lists"), ("frame", "Oracle Applications")]
BOX = (212, 250, 100, 22)


def ev(kind: str, t: float, role: str, name: str, path: str, **extra: Any) -> dict[str, Any]:
    box = extra.pop("box", BOX)
    node = {"path": path, "role": role, "name": name, "states": ["enabled", "showing"]}
    node["box"] = list(box)
    return {"kind": kind, "t": t, "source": {"node": node, "chain": FORM, "window": 1}, **extra}


def clicked(it: Interpreter, t: float, path: str, old: str, new: str) -> None:
    it.feed(ev("mouse_pressed", t, "check box", "Active", path))
    it.feed(ev("state_changed", t + 0.005, "check box", "Active", path, old=old, new=new))
    it.feed(ev("mouse_clicked", t + 0.008, "check box", "Active", path))


def test_a_box_clicked_is_its_state_whether_or_not_it_had_the_focus() -> None:
    it = Interpreter()
    clicked(it, 1.0, "0/0/4", "checked", "(null)")  # no focus: only a click before
    it.feed(ev("focus", 1.2, "check box", "Active", "0/0/5"))  # the „…” came first meanwhile
    clicked(it, 2.0, "0/0/5", "(null)", "checked")
    assert [(a.type, a.seen.node.name if a.seen else None) for a in it.take()] == [
        ("uncheck", "Active"),
        ("check", "Active"),
    ]


def test_a_click_into_a_field_after_the_box_is_no_click_of_the_box() -> None:
    """The click into „Grouping Number” after the box: no step of the box (with the paths moved
    by the „…”, it named the box)."""
    it = Interpreter()
    it.feed(ev("focus", 0.5, "check box", "Active", "0/0/5"))
    clicked(it, 1.0, "0/0/4", "checked", "(null)")
    grouping = (212, 280, 60, 22)
    it.feed(ev("mouse_pressed", 2.0, "text", "Grouping Number", "0/0/5", box=grouping))
    it.feed(ev("mouse_clicked", 2.01, "text", "Grouping Number", "0/0/5", box=grouping))
    it.feed(ev("focus", 2.02, "text", "Grouping Number", "0/0/5", box=grouping))
    it.finish(3.0)
    assert [a.type for a in it.take()] == ["uncheck"]


def _event(seq: int, kind: str, name: str = "Active", role: str = "checkbox") -> TraceEvent:
    target = ElementInfo(tag=f"java:{role}", role=role, name=name)
    url = "java://oracle-applications/Price Lists"
    return TraceEvent(seq=seq, t=float(seq), type=kind, url=url, target=target)  # type: ignore[arg-type]


def _trace(*events: TraceEvent) -> Trace:
    header = TraceHeader(
        recording_id="t",
        started_at=datetime(2026, 10, 19, tzinfo=UTC),
        start_url="java://oracle-applications/",
        program="Oracle Applications",
    )
    return Trace(header=header, events=list(events), states={})


def test_the_same_box_ticked_and_unticked_in_turn_is_one_step_its_last_state() -> None:
    trace = _trace(
        _event(1, "uncheck"),
        _event(2, "check"),
        _event(3, "click"),
        _event(4, "click", "Save", "button"),
        _event(5, "uncheck"),
    )
    steps = [(a.kind, a.event.target.name) for a in normalize(trace).steps if a.event.target]
    assert steps == [("check", "Active"), ("click", "Save"), ("uncheck", "Active")]
