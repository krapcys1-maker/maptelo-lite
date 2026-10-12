"""Mapping a process that works in two applications: what the person copied from one screen
into another, and addresses typed by hand that name one record."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo, Trace, TraceEvent, TraceHeader, TraceState
from maptelo.trace.locators import candidates_for
from maptelo.trace.schema import DataRef

LIST, ERP = "http://wl.test", "http://erp.test"
FOUND = """- main:
  - heading "Wynik wyszukiwania" [level=2]
  - term: Nazwa
  - definition: Zbiciak i syn s.c.
  - term: Numer rachunku
  - definition: PL73437049919574900522116933
  - paragraph: Zbiciak i syn s.c. jest czynnym podatnikiem.
"""
FORM = """- main:
  - heading "Nowy dostawca" [level=1]
  - textbox "Nazwa"
  - textbox "Numer konta"
  - button "Zapisz"
"""


def found_by_its_words(info: ElementInfo) -> ElementInfo:
    return info.model_copy(update={"candidates": candidates_for(info)})


def field(name: str) -> ElementInfo:
    return found_by_its_words(ElementInfo(tag="input", role="textbox", name=name, label=name))


class Recording:
    """A person on the white list, then in the ERP: each call is what they did."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self.states: dict[str, TraceState] = {}

    def state(self, url: str, aria: str) -> str:
        state_id = f"s{len(self.states) + 1}"
        self.states[state_id] = TraceState(id=state_id, t=len(self.events), url=url, aria=aria)
        return state_id

    def add(self, kind: str, url: str, **fields: Any) -> None:
        number = len(self.events) + 1
        self.events.append(TraceEvent(seq=number, t=number, type=kind, url=url, **fields))  # type: ignore[arg-type]

    def trace(
        self, path: Path | None = None, data: DataRef | None = None, name: str = "r1"
    ) -> Trace:
        header = TraceHeader(
            recording_id=name,
            started_at=datetime(2026, 10, 8, tzinfo=UTC),
            start_url=f"{LIST}/",
            data=data,
        )
        return Trace(header=header, events=self.events, states=self.states, path=path)


def vendor(opened: str = f"{ERP}/dostawcy/nowy", typed: str = "Zbiciak i syn s.c.") -> Recording:
    r = Recording()
    start = r.state(f"{LIST}/", '- heading "Wykaz podatników VAT" [level=1]\n- textbox "NIP"\n')
    r.add("navigate", f"{LIST}/", value=f"{LIST}/", state_after=start)
    found = r.state(f"{LIST}/szukaj?nip=3123435783", FOUND)
    r.add("fill", f"{LIST}/", target=field("NIP"), value="3123435783", state_before=start)
    button = found_by_its_words(ElementInfo(tag="button", role="button", name="Szukaj"))
    r.add("click", f"{LIST}/", target=button, state_before=start, state_after=found)
    r.add("navigated", f"{LIST}/szukaj?nip=3123435783", state_before=start, state_after=found)
    form = r.state(opened, FORM)
    r.add("navigated", opened, state_before=found, state_after=form)
    r.add("fill", opened, target=field("Nazwa"), value=typed, state_before=form)
    return r


def test_a_value_copied_from_the_other_application_is_read_there() -> None:
    model = map_trace(vendor().trace()).model
    actions = [s.action.value for s in model.steps]
    assert actions == ["navigate", "fill", "click", "read", "navigate", "fill"]
    read = model.steps[3]
    assert read.save_as == "nazwa"
    assert read.target is not None
    assert read.target[0].model_dump(exclude_none=True) == {"role": "definition", "column": "Nazwa"}
    assert model.steps[-1].value == "$vars.nazwa"
    assert set(model.inputs) == {"nip"}


def test_a_value_of_the_sheet_stays_a_value_of_the_sheet(tmp_path: Path) -> None:
    """The name was on the screen and in the sheet the person worked from: the sheet is the
    work's source, so it stays its column."""
    (tmp_path / "dostawcy.csv").write_text("NIP;Nazwa\n3123435783;Zbiciak i syn s.c.\n", "utf-8")
    trace = vendor().trace(tmp_path / "trace.jsonl", DataRef(file="dostawcy.csv"))
    model = map_trace(trace).model
    assert "read" not in [s.action.value for s in model.steps]
    assert set(model.inputs) == {"nip", "nazwa"}


def test_a_value_only_inside_running_text_is_not_read() -> None:
    """Shown in a sentence, not under a term: a robot could not find it again by its words."""
    r = vendor(typed="Zbiciak i syn s.c. jest czynnym podatnikiem.")
    model = map_trace(r.trace()).model
    assert "read" not in [s.action.value for s in model.steps]
    assert "nazwa" in model.inputs


def test_an_address_that_names_a_record_is_opened_by_a_person() -> None:
    """Typed by hand, ``/zamowienia/2`` names one order: the same order for every row of the
    sheet would put each row's work into it (benchmark: p10)."""
    result = map_trace(vendor(opened=f"{ERP}/zamowienia/2").trace())
    opened = result.model.steps[4]
    assert opened.action.value == "navigate"
    assert opened.value == f"{ERP}/zamowienia/2"
    assert opened.executor.value == "human"
    assert any("wskazuje jeden rekord (2)" in note for note in result.notes)


def test_an_address_with_a_value_from_the_data_is_opened_for_each_record() -> None:
    result = map_trace(vendor(opened=f"{ERP}/kontrahenci/3123435783").trace())
    opened = result.model.steps[4]
    assert opened.value == f"{ERP}/kontrahenci/{{inputs.nip}}"
    assert opened.executor.value == "deterministic"


def test_the_same_copied_value_in_two_fields_is_read_once() -> None:
    r = vendor()
    form = r.events[-1].state_before
    short = field("Nazwa skrócona")
    r.add(
        "fill", f"{ERP}/dostawcy/nowy", target=short, value="Zbiciak i syn s.c.", state_before=form
    )
    model = map_trace(r.trace()).model
    assert [s.action.value for s in model.steps].count("read") == 1
    assert [s.value for s in model.steps[-2:]] == ["$vars.nazwa", "$vars.nazwa"]
    assert set(model.inputs) == {"nip"}


def test_a_small_number_typed_somewhere_does_not_name_the_record_in_an_address() -> None:
    """“2” was the quantity, and the order is /zamowienia/2 by chance: taken from the data,
    the address would open the order numbered like each row's quantity."""
    r = Recording()
    start = r.state(f"{LIST}/", '- heading "Wykaz podatników VAT" [level=1]\n')
    r.add("navigate", f"{LIST}/", value=f"{LIST}/", state_after=start)
    r.add(
        "fill", f"{LIST}/", target=field("Ilość"), value="2", state_before=start, state_after=start
    )
    order = r.state(f"{ERP}/zamowienia/2", FORM)
    r.add("navigated", f"{ERP}/zamowienia/2", state_before=start, state_after=order)
    opened = map_trace(r.trace()).model.steps[-1]
    assert opened.value == f"{ERP}/zamowienia/2"
    assert opened.executor.value == "human"
