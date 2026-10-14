"""What the person says of a step, in full (why, when, whether a person decides), kept by an
action of the step: on Studio's list while recording, or on the map afterwards."""

from __future__ import annotations

from maptelo.mapping import map_trace
from maptelo.model.schema import Executor
from maptelo.trace import ElementInfo
from tests.mapping.test_many_apps import ERP, Recording, field, found_by_its_words

URL = f"{ERP}/akceptacja"
FORM = """- main:
  - textbox "Numer faktury"
  - button "Szukaj"
  - button "Akceptuj"
"""


def recording() -> Recording:
    r = Recording()
    form = r.state(URL, FORM)
    r.add("navigate", URL, value=URL, state_after=form)
    r.add("fill", URL, target=field("Numer faktury"), value="SBI/1", state_before=form)
    find = found_by_its_words(ElementInfo(tag="button", role="button", name="Szukaj"))
    r.add("click", URL, target=find, state_before=form, state_after=form)
    accept = found_by_its_words(ElementInfo(tag="button", role="button", name="Akceptuj"))
    r.add("click", URL, target=accept, state_before=form, state_after=form, sent=["POST /ok"])
    return r


def test_a_step_said_in_full_by_its_action() -> None:
    notes = {
        3: "faktura musi być na liście",  # plain words: why
        4: {
            "text": "akceptuję zgodną fakturę",
            "when": "tylko gdy Netto = Netto WZ",
            "person": True,
        },
    }
    steps = {
        s.target[0].name: s
        for s in map_trace(recording().trace(), notes=notes).model.steps
        if s.target
    }
    assert steps["Szukaj"].note == "faktura musi być na liście"
    assert steps["Szukaj"].note_when is None
    accept = steps["Akceptuj"]
    assert accept.note == "akceptuję zgodną fakturę"
    assert accept.note_when == "tylko gdy Netto = Netto WZ"
    assert accept.person_decides
    assert accept.executor is Executor.HUMAN  # the person said so: a robot stops before it


def test_an_empty_description_takes_back_what_was_said() -> None:
    steps = map_trace(recording().trace(), notes={4: ""}).model.steps
    assert all(not s.note for s in steps)
