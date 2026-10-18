"""A click told late, after a burst of events the bridge was still describing, is one click:
the recorder waits for the bridge's events by the time it has delivered, not by the clock
(benchmark WCR: the calendar's next month written twice, its click told 0.37 s after its press,
while the press alone looked like a click whose window closed)."""

from typing import Any

import pytest

from maptelo.capture.java import JavaRecorder, JavaRecorderOptions
from maptelo.desktop.jab import Bridge, Node, Window
from maptelo.trace.io import load_trace

BUTTON = Node("0/1/2", "push button", "Następny miesiąc", states=frozenset({"showing"}))


class LateBridge(Bridge):
    """A bridge whose events come later than the clock: ``delivered`` lags behind it."""

    def __init__(self) -> None:
        super().__init__()
        self.window = Window(41, "Kalendarz", 7, True)
        self.now = 0.0
        self.through = 0.0

    def windows(self, *, pid: int | None = None, java_only: bool = True) -> list[Window]:
        return [self.window]

    def tree(self, hwnd: int, **kwargs: Any) -> list[Node]:
        return [Node("0", "dialog", "Kalendarz", states=frozenset({"showing"})), BUTTON]

    def node(self, hwnd: int, path: str) -> Node | None:
        return Node("0", "dialog", "Kalendarz")

    def table(self, hwnd: int, path: str, *, max_rows: int = 500) -> None:
        return None

    def clock(self) -> float:
        return self.now

    def delivered(self) -> float:
        return self.through

    def close(self) -> None:
        pass


@pytest.fixture
def recording(tmp_path, monkeypatch):
    bridge = LateBridge()
    monkeypatch.setattr("maptelo.capture.java.connect", lambda **kwargs: bridge)
    monkeypatch.setattr("maptelo.capture.java._KeySampler.maybe", lambda pid: None)
    recorder = JavaRecorder(tmp_path / "recording", JavaRecorderOptions(screenshots=False))
    yield recorder, bridge
    if recorder.writer is not None:
        recorder.writer.close()


def told(bridge: LateBridge, kind: str, t: float) -> None:
    source = {"node": BUTTON.to_dict(), "chain": [("dialog", "Kalendarz")], "window": 41}
    bridge._emit(kind, source, t=t)


def clicks(recorder: JavaRecorder) -> list[float]:
    trace = load_trace(recorder.stop())
    return [e.t for e in trace.events if e.type == "click"]


def test_a_click_told_after_a_burst_is_one_click(recording) -> None:
    recorder, bridge = recording
    recorder.start()
    bridge.now = bridge.through = 1.0
    told(bridge, "mouse_pressed", 1.0)
    recorder.pump()
    # 0.7 s later by the clock: a click lost (its window closed) would be told by now; the
    # bridge, still describing the calendar's 82 children, has delivered only up to 1.05
    bridge.now, bridge.through = 1.7, 1.05
    recorder.pump()
    told(bridge, "mouse_clicked", 1.37)  # its callback ran after the burst
    bridge.now = bridge.through = 1.8
    recorder.pump()
    assert clicks(recorder) == [pytest.approx(1.37, abs=0.01)]


def test_a_press_whose_click_never_comes_is_still_a_click(recording) -> None:
    """The bridge caught up and no click by then: the button closed its window before its
    release could be told (benchmark D06: Find in the Find window)."""
    recorder, bridge = recording
    recorder.start()
    bridge.now = bridge.through = 1.0
    told(bridge, "mouse_pressed", 1.0)
    recorder.pump()
    bridge.now = bridge.through = 1.7
    recorder.pump()
    assert clicks(recorder) == [pytest.approx(1.0, abs=0.01)]


def told_event(kind: str, t: float, role: str, path: str, *, window: int, **extra: Any) -> dict:
    node = {"path": path, "role": role, "name": "Wiersze pliku" if role == "table" else ""}
    node["states"] = ["enabled", "showing"]
    chain = [("frame", "WCR")] if window else []
    return {
        "kind": kind,
        "t": t,
        "source": {"node": node, "chain": chain, "window": window},
        **extra,
    }


def test_a_box_unticked_in_a_row_and_the_tables_click_are_one_act_across_batches() -> None:
    """The recorder takes the acts after each batch of events: the untick of a row's box may be
    taken before the table's click of the same press arrives (benchmark M3: „Importuj” of a
    row of „Wiersze pliku” unticked, then a click on the row's first cell written as a step)."""
    from maptelo.capture.java import Interpreter

    it = Interpreter()
    editor = {"role": "check box", "name": "", "index": -1, "states": ["enabled"]}
    it.feed(told_event("child_changed", 6.35, "table", "0/1/2", window=1, old=None, new=editor))
    it.feed(
        told_event("state_changed", 6.38, "check box", "0", window=0, old="checked", new="(null)")
    )
    assert [act.type for act in it.take()] == ["uncheck"]
    it.feed(told_event("mouse_clicked", 6.41, "table", "0/1/2", window=1))
    it.tick(6.5)
    assert it.take() == []


ROWS = Node("0/2", "table", "Wnioski do akceptacji", states=frozenset({"showing"}))


def test_a_double_click_whose_second_click_comes_late_is_one_double_click(recording) -> None:
    """The first click is not written as a click of its own while the bridge is still behind:
    quiet is quiet by what it has told (benchmark M4: a row opened by a double click written
    as one click, so the robot clicked once and the request never opened)."""
    recorder, bridge = recording
    recorder.start()

    def clicked(t: float) -> None:
        source = {"node": ROWS.to_dict(), "chain": [("dialog", "Kalendarz")], "window": 41}
        bridge._emit("mouse_pressed", source, t=t)
        bridge._emit("mouse_clicked", source, t=t + 0.02)

    bridge.now = bridge.through = 1.0
    clicked(1.0)
    bridge.now = bridge.through = 1.05
    recorder.pump()
    bridge.now, bridge.through = 1.9, 1.1  # quiet by the clock, the second click still coming
    recorder.pump()
    clicked(1.2)
    bridge.now = bridge.through = 1.95
    recorder.pump()
    trace = load_trace(recorder.stop())
    assert [(e.type, e.clicks) for e in trace.events] == [("click", 2)]
