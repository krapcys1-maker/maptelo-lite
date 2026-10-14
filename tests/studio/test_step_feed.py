"""The steps of a recording as it runs, for Studio's list to describe them one by one: read
from the trace file as the recorder writes it, each told once, in words a person reads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from maptelo.studio.jobs import Job
from maptelo.studio.recording import StepFeed, keep_note, step_words, written_notes


def line(**event: Any) -> str:
    return json.dumps({"kind": "event", **event}, ensure_ascii=False) + "\n"


def test_each_action_is_told_once_as_the_trace_grows(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps({"kind": "header", "recording_id": "r1"})
        + "\n"
        + line(seq=1, t=0.5, type="click", url="java://wcr/Import cennika",
               target={"role": "button", "name": "Przeglądaj…"})
        + line(seq=2, t=0.6, type="appeared", url="java://wcr/Import cennika"),
        encoding="utf-8",
    )  # fmt: skip
    feed = StepFeed(trace, "pl")
    assert feed.new() == [
        {"action": 1, "words": "Kliknięcie „Przeglądaj…” · okno „Import cennika”"}
    ]
    assert feed.new() == []  # told once
    with trace.open("a", encoding="utf-8") as more:
        more.write(line(seq=3, t=1.0, type="fill", url="http://erp.test/x", value="K0010%",
                        target={"role": "textbox", "name": "Cennik"}))  # fmt: skip
        more.write('{"kind": "event", "seq": 4, "type": "cli')  # a line still being written
    assert feed.new() == [{"action": 3, "words": "Wpisanie w „Cennik”: K0010%"}]
    with trace.open("a", encoding="utf-8") as rest:
        rest.write('ck", "url": "http://erp.test/x", "target": {"name": "Zapisz"}}\n')
    assert [s["action"] for s in feed.new()] == [4]


def test_a_secret_is_not_shown_and_english_words() -> None:
    typed = {"type": "fill", "value": "tajne", "secret": True, "target": {"label": "Hasło"}}
    assert step_words(typed, "pl") == "Wpisanie w „Hasło”"
    clicked = {"type": "click", "target": {"name": "Save"}}
    assert step_words(clicked, "en") == "Click on “Save”"


def test_the_feed_tells_the_job(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(line(seq=7, type="check", target={"name": "Pilne"}), encoding="utf-8")
    job = Job(id="j1", kind="record", title="t", process="p")
    StepFeed(trace, "pl").tell(job, 12)
    events = job.view(0)["events"]
    assert [(e["seq"], e["type"], e.get("action"), e.get("words")) for e in events] == [
        (1, "progress", None, None),
        (2, "step", 7, "Zaznaczenie „Pilne”"),  # the job's own numbering stays
    ]


def test_the_steps_written_as_the_recording_ends_are_told_too(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(line(seq=1, type="click", target={"name": "Zapisz"}), encoding="utf-8")
    job = Job(id="j1", kind="record", title="t", process="p")
    StepFeed(trace, "pl").tell(job)
    assert [(e["type"], e.get("action")) for e in job.view(0)["events"]] == [("step", 1)]


def test_a_step_described_in_full_is_kept_by_its_action(tmp_path: Path) -> None:
    keep_note(tmp_path, 5, "wybieram najnowszą fakturę")
    keep_note(tmp_path, 9, "akceptuję", "tylko gdy kwoty się zgadzają", person=True)
    assert written_notes(tmp_path) == {
        5: "wybieram najnowszą fakturę",
        9: {"text": "akceptuję", "when": "tylko gdy kwoty się zgadzają", "person": True},
    }
