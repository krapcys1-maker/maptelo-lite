# ruff: noqa: RUF001
"""Which clicks of a desktop program save, when its recording cannot see what is sent."""

from __future__ import annotations

from maptelo.mapping import map_trace
from maptelo.model.schema import RiskClass
from maptelo.trace import TraceState
from maptelo.trace.locators import candidates_for

from .test_normalize import Builder, element

FORM = "java://wcr/Import cennika"


def _clicked(name: str, dialog: str, role: str = "button", tag: str = "java:push button"):  # type: ignore[no-untyped-def]
    info = element(name, role=role, tag=tag, dialog=dialog)
    info.candidates = candidates_for(info)
    return info


def test_a_save_that_brings_up_a_progress_window_is_a_save() -> None:
    """„Importuj zaznaczone” brings up „Importowanie…”, which goes away by itself, and the
    person goes on in the form (benchmark M3): the click saves, and a dry run stops before it.
    The function „Import cennika” chosen in the navigator saves nothing."""
    b = Builder(start="java://wcr/")
    navigator = "java://wcr/Nawigator – WCR"
    b.states["s0"] = TraceState(id="s0", t=0, url=navigator, aria='- option "Import cennika"\n')
    b.states["s1"] = TraceState(
        id="s1", t=1, url=FORM, aria='- button "Importuj zaznaczone"\n- button "Zamknij"\n'
    )
    b.states["s2"] = TraceState(
        id="s2", t=2, url="java://wcr/Importowanie…", aria="- progressbar\n", window=1
    )
    function = _clicked("Import cennika", "Nawigator – WCR", role="option", tag="java:list item")
    b.add("click", target=function, url=navigator, state_before="s0", state_after="s1")
    imported = _clicked("Importuj zaznaczone", "Import cennika")
    b.add("click", target=imported, url=FORM, state_before="s1", state_after="s2")
    closed = _clicked("Zamknij", "Import cennika")
    b.add("click", target=closed, url=FORM, state_before="s1", state_after="s1")
    steps = map_trace(b.trace()).model.steps
    risks = {s.target[0].name: s.risk for s in steps if s.target}
    assert risks["Importuj zaznaczone"] is RiskClass.COMMIT
    assert risks["Import cennika"] is not RiskClass.COMMIT
