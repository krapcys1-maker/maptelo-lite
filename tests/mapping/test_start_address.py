"""A process recorded from the application's own address alone (http://minierp.test:8000, the
clean-Windows Lite test of 12.10): its first step opens "/", not an empty address (the SOP said
„adres ``”)."""

from __future__ import annotations

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo
from maptelo.trace.schema import Trace
from tests.mapping.test_many_apps import ERP, Recording, found_by_its_words

FORM = """- main:
  - heading "Customer prices" [level=1]
  - textbox "CPN"
  - button "Search"
"""


def test_the_first_page_of_the_bare_address_is_slash() -> None:
    r = Recording()
    form = r.state(f"{ERP}/pricing", FORM)
    r.add("navigate", ERP, value=ERP, state_after=form)
    box = found_by_its_words(ElementInfo(tag="input", role="textbox", name="CPN", label="CPN"))
    r.add("fill", f"{ERP}/pricing", target=box, value="48212-B", state_before=form)
    recorded = r.trace()
    trace = Trace(
        header=recorded.header.model_copy(update={"start_url": ERP}),
        events=recorded.events,
        states=recorded.states,
    )
    model = map_trace(trace).model
    first = model.steps[0]
    assert first.action.value == "navigate"
    assert first.value == "/"


def test_the_note_and_the_sentence_after_it_are_two_sentences() -> None:
    """„Nowa cena do akceptacji Mapę utworzono automatycznie…” (the clean-Windows Lite test of
    12.10: a note typed without a period)."""
    r = Recording()
    form = r.state(f"{ERP}/pricing", FORM)
    r.add("navigate", ERP, value=ERP, state_after=form)
    box = found_by_its_words(ElementInfo(tag="input", role="textbox", name="CPN", label="CPN"))
    r.add("fill", f"{ERP}/pricing", target=box, value="48212-B", state_before=form)
    recorded = r.trace()
    for note, said in [
        ("Nowa cena do akceptacji", "Nowa cena do akceptacji. Mapę utworzono automatycznie"),
        ("Cena z rabatem.", "Cena z rabatem. Mapę utworzono automatycznie"),
    ]:
        header = recorded.header.model_copy(update={"note": note})
        trace = Trace(header=header, events=recorded.events, states=recorded.states)
        assert (map_trace(trace).model.description or "").startswith(said)
