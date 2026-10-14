"""What the person says about a step goes with it into the map, the SOP, the report and the
diagram: said while recording (Studio's box, a "note" in the trace), it belongs to the act it
came after; written on the map afterwards (by the step's first action), it replaces that."""

from __future__ import annotations

from pathlib import Path

from maptelo.export import write_map_bundle
from maptelo.mapping import map_trace
from maptelo.trace import Trace, TraceEvent, load_trace
from minierp.scenarios import PROCESS

RECORDING = Path(__file__).resolve().parents[1] / "fixtures" / "recordings" / PROCESS
NEWEST = "Biorę najnowszą wersję ceny, bo starsze są już nieważne."


def with_notes(*said: tuple[float, str]) -> Trace:
    trace = load_trace(RECORDING / "01-login-single-version")
    seq = max(event.seq for event in trace.events)
    for t, text in said:
        seq += 1
        trace.events.append(TraceEvent(seq=seq, t=t, type="note", value=text))
    return trace


def step_of(trace: Trace, name: str):  # type: ignore[no-untyped-def]
    """The map's step whose first target names ``name``, and the model."""
    model = map_trace(trace).model
    return next(s for s in model.steps if s.target and s.target[0].name == name), model


def test_what_was_said_after_an_act_describes_its_step() -> None:
    trace = with_notes()
    fill = next(e for e in trace.actions() if e.target and e.target.name == "Price")
    noted = with_notes((fill.t + 0.4, NEWEST))
    step, model = step_of(noted, "Price")
    assert step.note == NEWEST
    assert [s.id for s in model.steps if s.note] == [step.id]  # no other step got it


def test_what_was_said_before_anything_describes_the_opening() -> None:
    model = map_trace(with_notes((0.0, "Zaczynam od listy cen klienta."))).model
    assert model.steps[0].action.value == "navigate"
    assert model.steps[0].note == "Zaczynam od listy cen klienta."


def test_a_description_written_on_the_map_replaces_what_was_said() -> None:
    trace = with_notes()
    save = next(e for e in trace.actions() if e.target and e.target.name == "Save")
    said = with_notes((save.t + 0.2, "Zapisuję."))
    written = map_trace(said, notes={save.seq: "Zapisuję dopiero po sprawdzeniu daty."}).model
    step = next(s for s in written.steps if s.target and s.target[0].name == "Save")
    assert step.note == "Zapisuję dopiero po sprawdzeniu daty."
    removed = map_trace(said, notes={save.seq: ""}).model
    assert not next(s for s in removed.steps if s.target and s.target[0].name == "Save").note


def test_the_documents_quote_the_description(tmp_path: Path) -> None:
    trace = with_notes()
    fill = next(e for e in trace.actions() if e.target and e.target.name == "Price")
    result = map_trace(with_notes((fill.t + 0.4, NEWEST)))
    write_map_bundle(result, tmp_path, lang="pl")
    sop = (tmp_path / "sop.md").read_text(encoding="utf-8")
    assert f"   - **Opis:** {NEWEST}" in sop
    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Opis:</b> Biorę najnowszą wersję ceny" in report
    assert NEWEST in (tmp_path / "process.bpmn").read_text(encoding="utf-8")
    in_english = map_trace(with_notes((fill.t + 0.4, NEWEST)), lang="en")
    write_map_bundle(in_english, tmp_path / "en", lang="en")
    english = (tmp_path / "en" / "sop.md").read_text(encoding="utf-8")
    assert f"   - **Description:** {NEWEST}" in english
