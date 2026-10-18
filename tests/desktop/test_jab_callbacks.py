"""Native callbacks must return to Java before asking it for information in return."""

from types import SimpleNamespace

import pytest

from maptelo.desktop import jab
from maptelo.desktop.jab import Bridge, Node


@pytest.fixture
def events(monkeypatch):
    bridge = Bridge(events=True)
    callbacks, read, released = {}, [], []
    setters = [
        "setFocusGainedFP",
        "setPropertyTextChangeFP",
        "setPropertyStateChangeFP",
        "setPropertyChildChangeFP",
        "setPropertyVisibleDataChangeFP",
    ]
    dll = SimpleNamespace()
    for name in setters:

        def register(callback, name=name):
            callbacks[name] = callback

        setattr(dll, name, register)
    bridge._d = dll
    bridge._subscribe()
    monkeypatch.setattr(
        bridge,
        "_place",
        lambda vm, src: read.append(src) or ("0/1", 41, [("frame", "Test")], None),
    )
    monkeypatch.setattr(
        bridge, "_node", lambda *args, **kwargs: Node("0/1", "text", "Field", text="new")
    )
    monkeypatch.setattr(bridge, "_brief", lambda vm, obj: {"name": str(obj)})
    monkeypatch.setattr(
        bridge,
        "_info",
        lambda *args: read.append("info") or SimpleNamespace(role_en_US="label", name="Status"),
    )
    monkeypatch.setattr(bridge, "_release", lambda vm, *objects: released.append((vm, objects)))
    return bridge, callbacks, read, released


def test_callbacks_do_not_call_back_into_java_and_keep_arrival_order(events, monkeypatch):
    bridge, callbacks, read, released = events
    monkeypatch.setattr(bridge, "clock", lambda: 3.0)
    callbacks["setFocusGainedFP"](1, 11, 21)
    callbacks["setPropertyStateChangeFP"](1, 12, 22, "enabled", "focused")
    callbacks["setPropertyChildChangeFP"](1, 13, 23, 31, 32)
    callbacks["setPropertyVisibleDataChangeFP"](1, 14, 24)
    assert read == []
    assert released == []
    monkeypatch.setattr(bridge, "clock", lambda: 9.0)
    bridge._read_pending_events()
    recorded = bridge.events()
    assert [e["kind"] for e in recorded] == [
        "focus",
        "state_changed",
        "child_changed",
        "visible_data_changed",
    ]
    # stamped as they came, in their order: alike times one millisecond apart
    assert [e["t"] for e in recorded] == [3.0, 3.001, 3.002, 3.003]
    assert recorded[1]["old"] == "enabled"
    assert recorded[1]["new"] == "focused"
    assert recorded[2]["new"] == {"name": "32"}
    assert released == [(1, (11, 21)), (1, (12, 22)), (1, (13, 23, 31, 32)), (1, (14, 24))]


def test_a_failed_description_releases_objects_and_next_event_is_delivered(events, monkeypatch):
    bridge, callbacks, _, released = events

    def describe(vm, src):
        if src == 21:
            raise jab.StaleNodeError("gone")
        return "0/1", 41, [("frame", "Test")], None

    monkeypatch.setattr(bridge, "_place", describe)
    callbacks["setFocusGainedFP"](1, 11, 21)
    callbacks["setPropertyTextChangeFP"](1, 12, 22)
    bridge._read_pending_events()
    assert released == [(1, (11, 21)), (1, (12, 22))]
    assert bridge.events()[-1]["kind"] == "text_changed"


def test_shutdown_releases_pending_objects_without_reading_java(events):
    bridge, callbacks, read, released = events
    callbacks["setPropertyChildChangeFP"](1, 11, 21, 31, 32)
    bridge._read_pending_events(discard=True)
    assert read == []
    assert released == [(1, (11, 21, 31, 32))]
    assert bridge.events() == []
