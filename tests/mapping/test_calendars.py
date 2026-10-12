"""A day clicked in a calendar, on hand-made recordings: what opened the calendar, what moved
it, and what cannot be read (it stays a click, and the mapping says so)."""

from __future__ import annotations

from typing import Any

from maptelo.mapping import map_trace, normalize
from maptelo.trace import ElementInfo
from maptelo.trace.locators import candidates_for
from maptelo.trace.schema import CalendarSeen

from .test_normalize import URL, Builder, element, field

BOX = ElementInfo(tag="div", classes="div.picker", bbox=(400, 300, 300, 260))
FIELD = field("Termin").model_copy(update={"bbox": (100, 300, 200, 30), "css": "#termin"})


def days(month: int = 31) -> list[str]:
    return [str(day) for day in range(1, month + 1)]


def seen(**fields: Any) -> CalendarSeen:
    data: dict[str, Any] = {
        "days": days(),
        "index": 23,
        "role": "button",
        "texts": ["December 2026"],
        "controls": [
            element("", bbox=(400, 300, 30, 30)),  # arrows saying nothing
            element("December 2026", bbox=(440, 300, 200, 30)),
            element("", bbox=(670, 300, 30, 30)),
        ],
        "box": BOX,
        "field": FIELD,
    }
    data.update(fields)
    return CalendarSeen(**data)


def day(name: str = "24", **fields: Any) -> ElementInfo:
    clicked = element(name, bbox=(500, 450, 30, 30), calendar=seen(**fields))
    clicked.candidates = candidates_for(clicked)  # as the recorder writes them
    return clicked


def test_a_click_before_the_calendar_that_did_not_open_it_stays_a_step() -> None:
    """ "Add a line" opened a form; going into its date field (no step of its own) opened the
    calendar. The click before is no opener, and the field is what the robot clicks."""
    b = Builder()
    b.add("navigate", value=URL)
    b.add("click", target=element("Add a line", bbox=(50, 100, 80, 30)))
    b.add("click", target=element("", bbox=(670, 300, 30, 30)))  # the arrow on the right
    b.add("click", target=day())
    normalized = normalize(b.trace())
    assert [(a.kind, a.role) for a in normalized.acts] == [
        ("navigate", "step"), ("click", "step"), ("click", "superseded"), ("click", "step"),
    ]  # fmt: skip
    picked = normalized.acts[-1].picked
    assert picked is not None
    assert (picked.day.isoformat(), picked.pattern, picked.month) == (
        "2026-12-24", "{d}", "{Month_en} {yyyy}",
    )  # fmt: skip
    assert picked.target == FIELD
    assert picked.opens
    assert picked.label == "Termin"
    assert picked.previous is not None
    assert picked.next is not None
    assert (picked.previous.bbox, picked.next.bbox) == ((400, 300, 30, 30), (670, 300, 30, 30))


def test_a_day_of_two_months_of_plain_numbers_stays_a_click_and_says_so() -> None:
    b = Builder()
    b.add("navigate", value=URL)
    b.add("click", target=day(days=days() + days(30), texts=["December 2026", "January 2027"]))
    result = map_trace(b.trace())
    assert [s.action.value for s in result.model.steps] == ["navigate", "click"]
    assert any("nie dało się odczytać jako daty" in note for note in result.notes)


def test_numbers_that_are_no_month_are_no_calendar() -> None:
    """A pager of 40 pages around the clicked "24": no month over them, nothing is merged
    and nothing is said (it is no calendar)."""
    b = Builder()
    b.add("navigate", value=URL)
    pages = [str(n) for n in range(1, 41)]
    b.add("click", target=day(days=pages, texts=["Strony"], controls=[]))
    result = map_trace(b.trace())
    assert [s.action.value for s in result.model.steps] == ["navigate", "click"]
    assert not any("kalendarza" in note for note in result.notes)


def test_a_recording_made_before_the_recorder_saw_calendars_is_read_from_the_screen() -> None:
    """Recordings made before (the benchmark's g005): no calendar written down at the day,
    yet the screen before the click shows the window, its days named by their dates and its
    arrows."""
    cells = "\n".join(f'      - gridcell "{n} listopada 2026": "{n}"' for n in range(1, 31))
    b = Builder()
    shown = b.state(
        "s1",
        '- textbox "Termin"\n- button "Wybierz datę: Termin"\n- dialog "Kalendarz":\n'
        '  - button "Poprzedni miesiąc"\n  - text: Listopad 2026\n'
        f'  - button "Następny miesiąc"\n  - grid:\n{cells}\n',
    )
    after = b.state("s2", '- textbox "Termin": 2026-11-24\n')
    b.add("navigate", value=URL)
    b.add("click", target=element("Wybierz datę: Termin"))
    b.add("click", target=element("Następny miesiąc", dialog="Kalendarz"), state_before=shown)
    b.add(
        "click",
        target=element("24 listopada 2026", role="gridcell", tag="div", dialog="Kalendarz"),
        state_before=shown,
        state_after=after,
    )
    acts = normalize(b.trace()).acts
    assert [a.role for a in acts] == ["step", "superseded", "superseded", "step"]
    picked = acts[-1].picked
    assert picked is not None
    assert (picked.day.isoformat(), picked.pattern) == ("2026-11-24", "{d} {month} {yyyy}")
    assert picked.target.name == "Wybierz datę: Termin"
    assert picked.label == "Termin"  # the field that shows the day once it is clicked
    assert picked.box is not None
    assert picked.box.name == "Kalendarz"
    assert picked.next is not None
    assert picked.next.name == "Następny miesiąc"


def test_a_table_of_dates_is_no_calendar() -> None:
    """Thirty invoices, each with its date, one clicked: dates, but no month shown whole.
    The click stays a click (opening that invoice), and nothing is said about calendars."""
    dates = [f"2026-{month:02d}-{day:02d}" for month in (9, 10, 11) for day in (3, 9, 14, 20, 27)]
    dates += [f"2027-{month:02d}-11" for month in range(1, 13)] + ["2027-12-24", "2028-01-05"]
    b = Builder()
    b.add("navigate", value=URL)
    clicked = dates.index("2026-10-14")
    b.add("click", target=day(dates[clicked], days=dates, index=clicked, role="cell", texts=[]))
    result = map_trace(b.trace())
    assert [s.action.value for s in result.model.steps] == ["navigate", "click"]
    assert not any("kalendarza" in note for note in result.notes)


def test_the_step_before_a_day_picked_does_not_wait_for_that_day() -> None:
    """A field typed right before the calendar's day (benchmark g005): the day is the record's,
    not what the field's typing shows; expecting it made every other record fail."""
    b = Builder()
    b.add("navigate", value=URL, state_after="s1")
    b.state("s1", '- main:\n  - textbox "Uwagi"\n  - textbox "Termin"\n')
    remark = field("Uwagi")
    remark.candidates = candidates_for(remark)  # as the recorder writes them
    opener = FIELD.model_copy()
    opener.candidates = candidates_for(opener)
    b.add("fill", target=remark, value="pilne", state_before="s1", state_after="s2")
    b.state("s2", '- main:\n  - textbox "Uwagi"\n  - gridcell "24"\n')
    b.add("click", target=opener, state_before="s1", state_after="s2")
    b.add("click", target=day(), state_before="s2", state_after="s2")
    model = map_trace(b.trace()).model
    typed = next(s for s in model.steps if s.action.value == "fill")
    assert typed.expect is None
    assert typed.outcomes is None
