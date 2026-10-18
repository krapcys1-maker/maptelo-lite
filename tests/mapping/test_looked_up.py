"""What a person copied off a screen (Ctrl+C) and typed nowhere is what they came to look up:
the map reads it there, named after its words, for the run to hand back."""

from __future__ import annotations

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo

from .test_many_apps import LIST, Recording, field, found_by_its_words

CARD = """- main:
  - heading "Karta klienta" [level=1]
  - term: Klient
  - definition: C001
  - term: Saldo
  - definition: 1 250,00 zł
  - term: Limit
  - definition: 1 250,00 zł
  - table "Faktury":
    - rowgroup:
      - row "Numer Kwota":
        - columnheader "Numer"
        - columnheader "Kwota"
    - rowgroup:
      - row "FV/2026/0007 310,00 zł":
        - cell "FV/2026/0007"
        - cell "310,00 zł"
"""


def lookup(*copies: tuple[str, ElementInfo | None]) -> Recording:
    r = Recording()
    start = r.state(f"{LIST}/", '- heading "Klienci" [level=1]\n- textbox "Klient"\n')
    r.add("navigate", f"{LIST}/", value=f"{LIST}/", state_after=start)
    card = r.state(f"{LIST}/karta?klient=C001", CARD)
    r.add("fill", f"{LIST}/", target=field("Klient"), value="C001", state_before=start)
    button = found_by_its_words(ElementInfo(tag="button", role="button", name="Szukaj"))
    r.add("click", f"{LIST}/", target=button, state_before=start, state_after=card)
    r.add("navigated", f"{LIST}/karta?klient=C001", state_before=start, state_after=card)
    for value, target in copies:
        r.add("copied", f"{LIST}/karta", value=value, target=target, state_before=card)
    return r


def test_a_copied_value_is_read_where_it_stood_and_named_after_its_words() -> None:
    cell = ElementInfo(tag="td", role="cell", name="FV/2026/0007", column="Numer")
    model = map_trace(lookup(("FV/2026/0007", cell), ("C001", None)).trace()).model
    assert [s.action.value for s in model.steps] == ["navigate", "fill", "click", "read"]
    read = model.steps[-1]
    assert read.save_as == "numer"
    assert read.target is not None
    assert read.target[0].model_dump(exclude_none=True) == {"role": "cell", "column": "Numer"}
    assert read.within is not None
    assert read.within.where == {}  # the only row
    assert set(model.inputs) == {"klient"}  # the customer typed is no answer


def test_a_value_shown_twice_alike_is_not_read_but_said() -> None:
    """„1 250,00 zł” is the balance and the limit: which one the person read is not clear."""
    result = map_trace(lookup(("1 250,00 zł", None)).trace())
    assert "read" not in [s.action.value for s in result.model.steps]
    assert any("1 250,00 zł" in note for note in result.notes)


GRID = """- main:
  - heading "Reviews" [level=1]
  - text: 6 records found
  - table "Reviews":
    - rowgroup:
      - row "Title":
        - columnheader "Title"
"""


def counted(css: str) -> Recording:
    r = Recording()
    start = r.state(f"{LIST}/reviews", GRID.replace("6 records", "346 records"))
    r.add("navigate", f"{LIST}/reviews", value=f"{LIST}/reviews", state_after=start)
    grid = r.state(f"{LIST}/reviews", GRID)
    term = field("Review")
    r.add("fill", f"{LIST}/reviews", target=term, value="disappointed", state_before=start)
    button = found_by_its_words(ElementInfo(tag="button", role="button", name="Search"))
    r.add("click", f"{LIST}/reviews", target=button, state_before=start, state_after=grid)
    count = found_by_its_words(ElementInfo(tag="span", text="6", css=css))
    r.add("copied", f"{LIST}/reviews", value="6", target=count, state_before=grid)
    return r


def test_a_number_without_words_of_its_own_is_read_from_its_element_by_its_id() -> None:
    """„6” of „6 records found” stands in a span of its own: read there by the span's id, named
    after the words that follow it."""
    model = map_trace(counted("#reviewGrid-total-count").trace()).model
    read = model.steps[-1]
    assert (read.action.value, read.save_as) == ("read", "records_found")
    assert read.target is not None
    assert [r.model_dump(exclude_none=True) for r in read.target] == [
        {"css": "#reviewGrid-total-count"}
    ]


def test_an_element_found_only_by_where_it_stands_is_not_read() -> None:
    result = map_trace(counted("div:nth-of-type(2) > span").trace())
    assert "read" not in [s.action.value for s in result.model.steps]
    assert any("„6”" in note for note in result.notes)


def test_a_button_that_only_filters_a_list_does_not_save_by_its_words() -> None:
    """„Apply Filters” narrows the orders down (WebArena-Verified 253): a list looked at, not a
    save; „Apply” alone stays a save by its words, when the recording cannot tell."""
    r = Recording()
    start = r.state(f"{LIST}/orders", '- heading "Orders" [level=1]\n')
    r.add("navigate", f"{LIST}/orders", value=f"{LIST}/orders", state_after=start)
    for words in ("Apply Filters", "Apply"):
        button = found_by_its_words(ElementInfo(tag="button", role="button", name=words))
        r.add("click", f"{LIST}/orders", target=button, state_before=start, state_after=start)
    steps = map_trace(r.trace()).model.steps
    assert [s.effective_risk.value for s in steps[1:]] == ["draft", "commit"]
