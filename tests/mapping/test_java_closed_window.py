"""A desktop program's window that closes as its button is clicked: Java's file chooser (benchmark
M3), whose Open the bridge tells in no window at all, with the screen under it read."""

from __future__ import annotations

from maptelo.mapping import map_trace
from maptelo.trace import TraceState
from maptelo.trace.locators import candidates_for

from .test_normalize import Builder, element, field

FORM = "java://wcr/Import cennika"
CHOOSER = "java://wcr/Otwórz plik cennika"
SCREEN = '- button "Przeglądaj…"\n- textbox "Plik"\n- table "Wiersze pliku"\n'
PATH = "C:/Zespol/Cenniki/cennik_K0010_2026-11.csv"


def _clicked(name: str, dialog: str | None):  # type: ignore[no-untyped-def]
    info = element(name, tag="java:push button", dialog=dialog)
    info.candidates = candidates_for(info)
    return info


def test_the_open_of_a_file_chooser_is_in_the_chooser_and_closes_it() -> None:
    b = Builder(start="java://wcr/")
    b.states["s1"] = TraceState(id="s1", t=1, url=FORM, aria=SCREEN)
    b.add("click", target=_clicked("Przeglądaj…", "Import cennika"), url=FORM,
          state_before="s1", state_after="s1")  # fmt: skip
    name = field("File Name:").model_copy(update={"dialog": "Otwórz plik cennika"})
    name.candidates = candidates_for(name)
    b.add("fill", target=name, value=PATH, url=CHOOSER, window=1, state_before="s1",
          state_after="s1")  # fmt: skip
    b.add("click", target=_clicked("Open", None), url="java://wcr/", state_before="s1",
          state_after="s1")  # fmt: skip
    b.add("click", target=_clicked("Importuj zaznaczone", "Import cennika"), url=FORM,
          state_before="s1", state_after="s1")  # fmt: skip
    trace = b.trace()
    trace.header.program = "WCR"
    steps = {s.target[0].name: s for s in map_trace(trace).model.steps if s.target}
    assert steps["Open"].window == 1
    assert steps["Open"].closes_window
    assert steps["Open"].intent == "W oknie „Otwórz plik cennika” kliknij „Open”"
    assert not steps["File Name:"].closes_window


def test_a_button_the_screen_under_it_has_stays_there() -> None:
    """The screen read before the click has the button: the click may have been there."""
    b = Builder(start="java://wcr/")
    b.states["s1"] = TraceState(id="s1", t=1, url=FORM, aria=SCREEN + '- button "Open"\n')
    name = field("File Name:").model_copy(update={"dialog": "Otwórz plik cennika"})
    b.add("fill", target=name, value=PATH, url=CHOOSER, window=1, state_before="s1",
          state_after="s1")  # fmt: skip
    b.add("click", target=_clicked("Open", None), url="java://wcr/", state_before="s1",
          state_after="s1")  # fmt: skip
    trace = b.trace()
    trace.header.program = "WCR"
    steps = {s.target[0].name: s for s in map_trace(trace).model.steps if s.target}
    assert steps["Open"].window == 0
