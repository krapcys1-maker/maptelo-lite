"""A desktop program's calendar is a window of its own, opened by a button next to its field
(WCR's „Wybierz datę: Obowiązuje od”, benchmark M1). The day picked there fills a field one can
type into as well: the step is the date typed into that field, the same step as in the
recordings of people who typed it, and the one the Java robot can do."""

from __future__ import annotations

from maptelo.mapping import map_trace
from maptelo.model.schema import Action
from maptelo.trace import TraceState
from maptelo.trace.locators import candidates_for

from .test_normalize import Builder, element

REQUEST = "java://wcr/Nowa wersja ceny"
CALENDAR = "java://wcr/Kalendarz"
MONTHS = "listopada"


def _form(date: str) -> str:
    shown = f": {date}" if date else ""
    return (
        '- textbox "Kontrahent": K0010\n'
        f'- textbox "Obowiązuje od"{shown}\n'
        '- button "Wybierz datę: Obowiązuje od"\n'
        '- button "Zapisz"\n'
    )


def _calendar() -> str:
    days = "".join(f'- button "{d} {MONTHS} 2026"\n' for d in range(1, 31))
    return (
        '- text: Listopad 2026\n- button "Poprzedni miesiąc"\n- button "Następny miesiąc"\n' + days
    )


def _clicked(name: str, dialog: str):  # type: ignore[no-untyped-def]
    info = element(name, tag="java:push button", dialog=dialog)
    info.candidates = candidates_for(info)
    return info


def test_a_day_picked_in_a_programs_calendar_is_the_date_typed_into_its_field() -> None:
    b = Builder(start="java://wcr/")
    b.states["s1"] = TraceState(id="s1", t=1, url=REQUEST, aria=_form(""))
    b.states["s2"] = TraceState(id="s2", t=2, url=CALENDAR, aria=_calendar())
    b.states["s3"] = TraceState(id="s3", t=3, url=REQUEST, aria=_form("2026-11-01"))
    b.add("click", target=_clicked("Wybierz datę: Obowiązuje od", "Nowa wersja ceny"), url=REQUEST,
          state_before="s1", state_after="s2")  # fmt: skip
    b.add("click", target=_clicked("1 listopada 2026", "Kalendarz"), url=CALENDAR,
          state_before="s2", state_after="s3")  # fmt: skip
    b.add("click", target=_clicked("Zapisz", "Nowa wersja ceny"), url=REQUEST,
          state_before="s3", state_after="s3")  # fmt: skip
    steps = map_trace(b.trace()).model.steps
    typed = [s for s in steps if s.action is Action.FILL]
    assert len(typed) == 1, [(s.action, s.intent) for s in steps]
    assert typed[0].target is not None
    assert typed[0].target[0].name == "Obowiązuje od"
    assert not any(s.target and "Wybierz datę" in (s.target[0].name or "") for s in steps)
    assert not any(s.target and "listopada" in (s.target[0].name or "") for s in steps)
    assert any(s.target and s.target[0].name == "Zapisz" for s in steps)


def test_a_day_picked_in_a_calendar_the_recording_did_not_read_is_still_the_date_typed() -> None:
    """The program told the calendar's window late and the recording read the main window
    instead (benchmark M1 r2): the day's name says the date, the button that opened the
    calendar says the field, a later screen shows how the field writes it."""
    main = '- region "Wnioski o zmianę ceny":\n  - button "Nowy wniosek"\n'
    b = Builder(start="java://wcr/")
    b.states["s1"] = TraceState(id="s1", t=1, url=REQUEST, aria=_form(""))
    b.states["s2"] = TraceState(id="s2", t=2, url="java://wcr/Wnioski o zmianę ceny", aria=main)
    b.states["s3"] = TraceState(id="s3", t=3, url=REQUEST, aria=_form("2026-11-01"))
    b.add("click", target=_clicked("Wybierz datę: Obowiązuje od", "Nowa wersja ceny"), url=REQUEST,
          state_before="s1", state_after="s2")  # fmt: skip
    b.add("click", target=_clicked("Następny miesiąc", "Kalendarz"), url=CALENDAR,
          state_before="s2", state_after="s2")  # fmt: skip
    b.add("click", target=_clicked("1 listopada 2026", "Kalendarz"), url=CALENDAR,
          state_before="s2", state_after="s2")  # fmt: skip
    b.add("click", target=_clicked("Zapisz", "Nowa wersja ceny"), url=REQUEST,
          state_before="s3", state_after="s3")  # fmt: skip
    steps = map_trace(b.trace()).model.steps
    typed = [s for s in steps if s.action is Action.FILL]
    assert [s.target[0].name for s in typed if s.target] == ["Obowiązuje od"]
    named = [s.target[0].name or "" for s in steps if s.target]
    assert not any("Wybierz datę" in n or "listopada" in n or "miesiąc" in n for n in named)


def test_a_double_clicked_row_is_a_double_click_step() -> None:
    """A request opened from the list with a double click (benchmark M4): the step says so,
    and a robot double-clicks too."""
    from maptelo.trace.schema import RowContext

    approvals = "java://wcr/Akceptacje wniosków"
    request = "java://wcr/Wniosek WC/2026/000104"
    table = "\n".join(
        [
            '- table "Wnioski do akceptacji":',
            "  - row:",
            '    - columnheader "Nr"',
            "  - row:",
            "    - cell: WC/2026/000104",
            "  - row:",
            "    - cell: WC/2026/000105",
        ]
    )
    b = Builder(start="java://wcr/")
    b.states["s1"] = TraceState(id="s1", t=1, url=approvals, aria=table)
    b.states["s2"] = TraceState(id="s2", t=2, url=request, aria='- button "Zatwierdź decyzję"')
    row = element(
        "WC/2026/000104", role="cell", tag="java:table cell", dialog="Akceptacje wniosków"
    )
    row.row = RowContext(table="Wnioski do akceptacji", cells={"Nr": "WC/2026/000104"}, index=0)
    row.column = "Nr"
    row.candidates = candidates_for(row)
    b.add("click", target=row, url=approvals, clicks=2, state_before="s1", state_after="s2")
    decide = _clicked("Zatwierdź decyzję", "Wniosek WC/2026/000104")
    b.add("click", target=decide, url=request, state_before="s2", state_after="s2")
    steps = map_trace(b.trace()).model.steps
    opened = [s for s in steps if s.clicks == 2]
    assert len(opened) == 1, [(s.intent, s.clicks) for s in steps]
    assert opened[0].intent.endswith("(dwuklikiem)")
