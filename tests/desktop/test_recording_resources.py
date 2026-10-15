"""Failed recordings release their real files and connection; minimized forms are not read."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from maptelo.capture.java import JavaRecorder, JavaRecorderOptions
from maptelo.desktop.jab import AccessBridgeError, Bridge, Node, Window
from maptelo.studio.discard import discard


class RecordingBridge(Bridge):
    def __init__(self) -> None:
        super().__init__()
        self.window = Window(41, "Test Java", 7, True)
        self.closed = 0
        self.reads = 0
        self.fail = False

    def windows(self, *, pid=None, java_only=True):
        if self.fail:
            raise AccessBridgeError("connection lost")
        return [self.window]

    def tree(self, hwnd, **kwargs):
        self.reads += 1
        return [Node("0", "frame", "Test Java", states=frozenset({"showing"}))]

    def node(self, hwnd, path):
        return Node("0", "frame", "Test Java")

    def close(self):
        self.closed += 1


@pytest.fixture
def recording(tmp_path, monkeypatch):
    bridge = RecordingBridge()
    monkeypatch.setattr("maptelo.capture.java.connect", lambda **kwargs: bridge)
    monkeypatch.setattr("maptelo.capture.java._KeySampler.maybe", lambda pid: None)
    recorder = JavaRecorder(tmp_path / "recording", JavaRecorderOptions(screenshots=False))
    yield recorder, bridge
    # Also clean up on the old, failing implementation, so the fixture can be removed.
    if recorder.writer is not None:
        recorder.writer.close()


@pytest.mark.parametrize("failure", ["start", "pump", "stop"])
def test_failure_closes_the_trace_and_bridge(recording, monkeypatch, failure):
    recorder, bridge = recording

    def broken(*args, **kwargs):
        raise AccessBridgeError("connection lost")

    if failure == "start":
        monkeypatch.setattr(recorder, "_capture", broken)
    else:
        recorder.start()
        if failure == "pump":
            bridge.fail = True
        else:
            monkeypatch.setattr(recorder, "pump", lambda: 0)
            monkeypatch.setattr(recorder.interpreter, "finish", broken)
    run = {"start": recorder.start, "pump": recorder.record_until, "stop": recorder.stop}[failure]
    with pytest.raises(AccessBridgeError, match="connection lost"):
        run()
    assert recorder.writer is not None
    assert recorder.writer.closed
    assert bridge.closed == 1
    # Windows really moves this newly made folder to the Bin. No fake unlink/rmtree.
    discard([recorder.folder])
    assert not recorder.folder.exists()


def test_a_borrowed_bridge_is_not_closed(recording):
    recorder, bridge = recording
    recorder.bridge, recorder._own_bridge = bridge, False
    recorder.start()
    bridge.fail = True
    with pytest.raises(AccessBridgeError):
        recorder.record_until()
    assert recorder.writer.closed
    assert bridge.closed == 0


def test_minimize_and_restore_with_the_same_handle(recording):
    recorder, bridge = recording
    recorder.start()
    initial_reads = bridge.reads
    bridge.window = replace(bridge.window, minimized=True)
    recorder.pump()
    assert recorder._screen(bridge.window.hwnd) is None
    assert bridge.reads == initial_reads
    # Restore does not open a new window or change its handle.
    bridge.window = replace(bridge.window, minimized=False)
    recorder.pump()
    assert recorder._screen(bridge.window.hwnd) is not None
    assert bridge.reads == initial_reads + 1
    recorder.close()


def test_stop_can_be_repeated_without_reopening_or_rereading(recording):
    recorder, bridge = recording
    recorder.start()
    path = recorder.stop()
    reads = bridge.reads
    assert recorder.stop() == path
    assert bridge.closed == 1
    assert bridge.reads == reads


def test_hidden_controls_are_skipped_before_reading_their_text(monkeypatch):
    bridge = Bridge()
    info = SimpleNamespace(
        role="text",
        role_en_US="text",
        name="Hidden field",
        description="",
        states="enabled",
        states_en_US="enabled",
        accessibleText=True,
        accessibleAction=True,
        accessibleInterfaces=0,
        childrenCount=0,
        indexInParent=0,
        x=0,
        y=0,
        width=10,
        height=10,
    )
    monkeypatch.setattr(bridge, "_info", lambda *args: info)
    calls = []
    monkeypatch.setattr(bridge, "_read_text", lambda *args: calls.append("text") or "value")
    monkeypatch.setattr(bridge, "_actions", lambda *args: calls.append("actions") or ())
    assert bridge._node(1, 2, "0/0", showing_only=True) is None
    assert calls == []
    # Hidden list options are still readable when explicitly requested by chosen_in_lists.
    assert bridge._node(1, 2, "0/0").text == "value"
    assert calls == ["text", "actions"]
