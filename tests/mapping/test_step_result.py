"""What a step's result is (benchmark p16): „Dodaj pozycję” saves the line and shows the request
with „Dodano pozycję”; the person reads it and goes back to the list by its address. The list is
the person's next move, not the result of the click: the robot waits for the request's page."""

from __future__ import annotations

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo
from tests.mapping.test_many_apps import ERP, Recording, field, found_by_its_words

LIST = f"{ERP}/wnioski-cen"
REQUEST = f"{ERP}/wnioski-cen/70"
LISTED = """- main:
  - heading "Wnioski o zmianę cen" [level=1]
  - table "Wnioski o zmianę cen"
"""
OPENED = """- main:
  - heading "Wniosek ZC/2026/070" [level=1]
  - textbox "Nowa cena"
  - button "Dodaj pozycję"
  - table "Pozycje wniosku"
"""
ADDED = OPENED + '  - status: "Dodano pozycję."\n'


def test_the_result_of_a_step_is_where_it_led_not_where_the_person_went_next() -> None:
    r = Recording()
    opened = r.state(REQUEST, OPENED)
    r.add("navigate", REQUEST, value=REQUEST, state_after=opened)
    r.add("fill", REQUEST, target=field("Nowa cena"), value="6.04", state_before=opened)
    added = r.state(REQUEST, ADDED)
    listed = r.state(LIST, LISTED)
    add = found_by_its_words(ElementInfo(tag="button", role="button", name="Dodaj pozycję"))
    r.add("click", REQUEST, target=add, state_before=opened, state_after=added, sent=["POST /p"])
    r.add("navigated", REQUEST, state_before=opened, state_after=added)
    status = ElementInfo(tag="div", role="status", name="Dodano pozycję.")
    r.add("appeared", REQUEST, target=status, state_before=added, state_after=added)
    r.add("navigated", LIST, state_before=added, state_after=listed)  # the person goes on
    model = map_trace(r.trace()).model
    step = next(s for s in model.steps if s.target and s.target[0].name == "Dodaj pozycję")
    assert step.expect is not None
    listed_state = next(k for k, v in model.states.items() if v.url == "/wnioski-cen")
    expected = step.expect.model_dump(exclude_none=True)
    assert expected != {"state": listed_state}  # not the list the person went to
    assert expected == {"visible": {"role": "status"}}  # „Dodano pozycję.” on the request


def test_search_can_show_a_table_without_changing_the_url():
    from maptelo.trace.schema import RowContext

    r = Recording()
    url = ERP + "/search"
    before = r.state(url, '- textbox "Product"\n- button "Search"\n')
    after = r.state(url, '- table "Versions"\n')
    r.add("navigate", url, value=url, state_after=before)
    r.add(
        "click",
        url,
        target=found_by_its_words(ElementInfo(tag="button", role="button", name="Search")),
        state_before=before,
        state_after=after,
    )
    r.add(
        "click",
        url,
        target=found_by_its_words(
            ElementInfo(
                tag="a",
                role="link",
                name="Select",
                column="Action",
                row=RowContext(table="Versions", cells={"Status": "Active", "Action": "Select"}),
            )
        ),
        state_before=after,
        state_after=after,
    )
    model = map_trace(r.trace()).model
    search = next(s for s in model.steps if s.target and s.target[0].name == "Search")
    assert search.expect.model_dump(exclude_none=True) == {
        "visible": {"role": "table", "name": "Versions"}
    }
