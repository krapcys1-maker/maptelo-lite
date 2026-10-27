"""A list-of-values button nothing names („…” by a field in Oracle Forms, a calendar's too) is
known by the field it stands beside: the step says which list it opens, and a robot opens it
(``test_java_run_beside``). Without a name its steps were „click element”, handed to a
person."""

from __future__ import annotations

from datetime import UTC, datetime

from maptelo.capture.java import _named_by_its_field
from maptelo.desktop.jab import Node
from maptelo.desktop.screen import build_screen
from maptelo.mapping import map_trace
from maptelo.model.schema import Locator
from maptelo.trace import ElementInfo, Trace, TraceEvent, TraceHeader

SHOWN = frozenset({"enabled", "showing", "visible", "focusable", "editable"})
NAME = (212, 160, 200, 22)
CURRENCY = (212, 190, 80, 22)
DOTS = (414, 160, 24, 22)  # right of „Name”


def form(*, button: bool, focused: str | None = None) -> list[Node]:
    def state(name: str) -> frozenset[str]:
        return SHOWN | {"focused"} if name == focused else SHOWN

    nodes = [
        Node("0", "frame", "Oracle Applications", states=SHOWN, box=(0, 0, 900, 560)),
        Node("0/1", "text", "Name RequiredList of Values", states=state("Name"), box=NAME),
        Node(
            "0/2", "text", "Currency RequiredList of Values", states=state("Currency"), box=CURRENCY
        ),
        Node("0/3", "tool bar", "", states=SHOWN, box=(0, 30, 900, 30)),
        Node("0/3/0", "push button", "", states=SHOWN, box=(2, 32, 26, 26)),
    ]
    if button:
        nodes.insert(1, Node("0/0", "push button", "", states=SHOWN - {"focusable"}, box=DOTS))
    return nodes


def test_a_button_without_a_name_is_known_by_the_field_on_its_left() -> None:
    screen = build_screen("Oracle Applications", 1, form(button=False))
    dots = ElementInfo(tag="java:push button", role="button", bbox=DOTS)
    named = _named_by_its_field(dots, screen)
    assert named.beside == "Name"
    assert named.candidates == [Locator(beside="Name")]
    toolbar = ElementInfo(tag="java:push button", role="button", bbox=(2, 32, 26, 26))
    toolbar = toolbar.model_copy(update={"css": "toolbar button #1"})
    assert _named_by_its_field(toolbar, screen).beside is None  # known by its place there
    far = ElementInfo(tag="java:push button", role="button", bbox=(700, 160, 24, 22))
    assert _named_by_its_field(far, screen).beside is None  # no field next to it
    named_button = ElementInfo(tag="java:push button", role="button", name="OK", bbox=DOTS)
    assert _named_by_its_field(named_button, screen).beside is None


def test_the_step_says_which_fields_button_it_clicks_and_a_robot_does_it() -> None:
    target = ElementInfo(
        tag="java:push button",
        role="button",
        bbox=DOTS,
        beside="Name",
        candidates=[Locator(beside="Name")],
    )
    url = "java://oracle-applications/Price Lists"
    events = [TraceEvent(seq=1, t=1.0, type="click", url=url, target=target)]
    header = TraceHeader(
        recording_id="r",
        started_at=datetime(2026, 10, 19, tzinfo=UTC),
        start_url="java://oracle-applications/",
        program="Oracle Applications",
    )
    steps = map_trace(Trace(header=header, events=events, states={})).model.steps
    clicked = steps[-1]
    assert clicked.intent == "Kliknij „…” przy polu „Name”"
    assert clicked.target == [Locator(beside="Name")]
    assert clicked.executor.value == "deterministic"
