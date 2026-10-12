"""A window over the main one at the main page's own address (benchmark g039: the approval opened
with window.open of the record's address) is a screen of its own: its step does not wait for the
main page's screen."""

from __future__ import annotations

from maptelo.mapping import map_trace
from maptelo.trace import TraceState
from maptelo.trace.locators import candidates_for

from .test_normalize import Builder, element

RECORD = "http://app.test/g/g039/rekord?numer=DE/2026/0001&strona=1"
MAIN = """- main:
  - heading "Delegacja DE/2026/0001" [level=1]
  - heading "Zmiana danych" [level=2]
  - textbox "Limit"
  - button "Akceptuj"
"""
APPROVAL = """- main:
  - heading "Zatwierdzenie zmian" [level=1]
  - button "Zatwierdź"
"""


def test_a_step_in_a_window_at_the_same_address_takes_that_windows_screen() -> None:
    b = Builder(start=RECORD)
    b.add("navigate", value=RECORD, url=RECORD, state_after="s1")
    b.states["s1"] = TraceState(id="s1", t=1, url=RECORD, aria=MAIN, window=0)
    accept = element("Akceptuj")
    accept.candidates = candidates_for(accept)
    b.add("click", target=accept, url=RECORD, state_before="s1", state_after="s2")
    b.add("navigated", url=RECORD, window=1, state_before="s1", state_after="s2")
    b.states["s2"] = TraceState(id="s2", t=2, url=RECORD, aria=APPROVAL, window=1)
    approve = element("Zatwierdź")
    approve.candidates = candidates_for(approve)
    b.add("click", target=approve, url=RECORD, window=1, state_before="s2", state_after="s3")
    b.states["s3"] = TraceState(id="s3", t=3, url=RECORD, aria=MAIN, window=0)
    model = map_trace(b.trace()).model
    step = next(s for s in model.steps if s.target and s.target[0].name == "Zatwierdź")
    assert step.window == 1
    assert step.in_state is not None
    shown = model.states[step.in_state].visible or []
    assert [(v.role, v.name) for v in shown] == [("heading", "Zatwierdzenie zmian")]
    main = next(s for s in model.steps if s.target and s.target[0].name == "Akceptuj")
    assert main.in_state != step.in_state
