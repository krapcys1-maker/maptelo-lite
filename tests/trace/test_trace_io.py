from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from maptelo.trace import (
    ElementInfo,
    TraceEnd,
    TraceError,
    TraceEvent,
    TraceHeader,
    TraceState,
    TraceWriter,
    load_trace,
)

NOW = datetime(2026, 10, 7, 6, 0, tzinfo=UTC)


def header() -> TraceHeader:
    return TraceHeader(recording_id="r1", started_at=NOW, start_url="http://app/start")


def write(path: Path, *records: object) -> Path:
    with TraceWriter(path) as writer:
        for record in records:
            writer.write(record)  # type: ignore[arg-type]
    return path


def test_round_trip(tmp_path: Path) -> None:
    click = TraceEvent(
        seq=1,
        t=0.5,
        type="click",
        target=ElementInfo(tag="button", role="button", name="Save"),
        state_before="s0001",
        state_after="s0002",
    )
    states = [TraceState(id=f"s000{i}", t=i, url="http://app/x", aria="- main") for i in (1, 2)]
    end = TraceEnd(t=1.0, ended_at=NOW, events=1, states=2)
    path = write(tmp_path / "trace.jsonl", header(), states[0], click, states[1], end)

    trace = load_trace(tmp_path)  # a folder works too
    assert trace.header.recording_id == "r1"
    assert [e.type for e in trace.actions()] == ["click"]
    assert trace.state("s0002") is not None
    assert trace.end is not None
    assert trace.path == path
    assert '"secret"' in path.read_text(encoding="utf-8")  # defaults are written explicitly


@pytest.mark.parametrize(
    ("records", "message"),
    [
        ([], "empty trace"),
        (["event"], "first record must be the header"),
        (["header", "header"], "a second header"),
        (["header", "end", "event"], "records after the end record"),
        (["header", "event", "event"], "event numbers must increase"),
        (["header", "dangling"], "unknown state 's9999'"),
    ],
)
def test_inconsistent_traces_are_rejected(tmp_path: Path, records: list[str], message: str) -> None:
    built = {
        "header": header(),
        "event": TraceEvent(seq=1, t=0, type="navigate", value="http://app/start"),
        "dangling": TraceEvent(seq=1, t=0, type="click", state_after="s9999"),
        "end": TraceEnd(t=0, ended_at=NOW, events=0, states=0),
    }
    write(tmp_path / "trace.jsonl", *(built[r] for r in records))
    with pytest.raises(TraceError, match=message):
        load_trace(tmp_path / "trace.jsonl")


def test_unknown_record_kind_is_reported_with_line(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    write(path, header())
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "gossip"}\n')
    with pytest.raises(TraceError, match=r"trace.jsonl:2:"):
        load_trace(path)


def _state(n: int) -> TraceState:
    return TraceState(id=f"s000{n}", t=n, url="http://app/x", aria="- main")


def test_a_line_separator_in_a_value_is_part_of_the_value(tmp_path: Path) -> None:
    said = "Uwaga" + chr(0x2028) + "druga linia"  # copied from a document with line separators
    typed = TraceEvent(seq=1, t=0.5, type="fill", value=said, state_before="s0001")
    write(tmp_path / "trace.jsonl", header(), _state(1), typed)
    assert load_trace(tmp_path).events[0].value == said


def test_a_recording_cut_off_is_read_up_to_where_it_stopped(tmp_path: Path) -> None:
    click = TraceEvent(seq=1, t=0.5, type="click", state_before="s0001", state_after="s0002")
    late = TraceEvent(seq=2, t=0.9, type="click", state_before="s0002", state_after="s0003")
    path = write(tmp_path / "trace.jsonl", header(), _state(1), click, _state(2), late)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "state", "id": "s0003", "t": 1.0, "url": "http://ap')  # power cut
    trace = load_trace(path)
    assert [e.seq for e in trace.events] == [1, 2]
    assert trace.events[1].state_before == "s0002"
    assert trace.events[1].state_after is None  # the screen it led to was never written
    assert trace.end is None


def test_a_screen_missing_inside_a_recording_is_still_refused(tmp_path: Path) -> None:
    lost = TraceEvent(seq=1, t=0.5, type="click", state_before="s0001", state_after="s0009")
    after = TraceEvent(seq=2, t=0.9, type="click", state_before="s0002")
    write(tmp_path / "trace.jsonl", header(), _state(1), lost, _state(2), after)
    with pytest.raises(TraceError, match="unknown state 's0009'"):
        load_trace(tmp_path)
