"""A button clicked again and again on one screen until something shows: a system gives a
status later („Sprawdź status w KSeF” until the invoice has its number). The clicks are one step
done until that shows, not as many steps as one person happened to click."""

from __future__ import annotations

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo
from tests.mapping.test_many_apps import ERP, Recording, found_by_its_words

URL = f"{ERP}/faktury/FV-2026-10-0007"


def screen(status: str) -> str:
    return (
        '- heading "Faktura FV/2026/10/0007" [level=1]\n'
        f'- cell "{status}"\n'
        '- button "Sprawdź status w KSeF"\n'
    )


def test_a_status_checked_until_it_comes_is_one_step_done_until_it_shows() -> None:
    r = Recording()
    waiting = r.state(URL, screen("Oczekuje na numer KSeF"))
    still = r.state(URL, screen("Oczekuje na numer KSeF"))
    came = r.state(URL, screen("Wysłana do KSeF"))
    r.add("navigate", URL, value=URL, state_after=waiting)
    check = found_by_its_words(
        ElementInfo(tag="button", role="button", name="Sprawdź status w KSeF")
    )
    r.add("click", URL, target=check, state_before=waiting, state_after=still)
    r.add("click", URL, target=check, state_before=still, state_after=still)
    r.add("click", URL, target=check, state_before=still, state_after=came)
    model = map_trace(r.trace()).model
    clicks = [s for s in model.steps if s.action.value == "click"]
    assert len(clicks) == 1
    repeat = clicks[0].repeat
    assert repeat is not None
    assert repeat.until.visible is not None
    assert repeat.until.visible.text == "Wysłana do KSeF"
    assert repeat.tries >= 5
    assert repeat.every_ms == 1000  # as long as the person waited between the clicks


def test_clicks_after_which_nothing_new_shows_stay_as_they_were() -> None:
    r = Recording()
    same = r.state(URL, screen("Oczekuje na numer KSeF"))
    r.add("navigate", URL, value=URL, state_after=same)
    check = found_by_its_words(
        ElementInfo(tag="button", role="button", name="Sprawdź status w KSeF")
    )
    r.add("click", URL, target=check, state_before=same, state_after=same)
    r.add("click", URL, target=check, state_before=same, state_after=same)
    model = map_trace(r.trace()).model
    assert not any(s.repeat for s in model.steps)
