"""Clicks inside table rows, as Odoo 18 lists them: a record picked by its only value."""

from __future__ import annotations

from typing import Any

from maptelo.mapping import map_trace, normalize
from maptelo.trace import ElementInfo
from maptelo.trace.locators import candidates_for
from maptelo.trace.schema import RowContext
from tests.mapping.test_normalize import URL, Builder, field

ROW = RowContext(cells={"#1": "", "Pricelist Name": "Ceny C001", "Country Groups": ""}, index=2)
ROW_CSS = "table > tbody > tr:nth-of-type(2) > td:nth-of-type({})"


def in_row(**fields: Any) -> ElementInfo:
    info = ElementInfo(**fields)
    return info.model_copy(update={"candidates": candidates_for(info)})


def last_step(*targets: ElementInfo) -> dict[str, Any]:
    b = Builder()
    b.add("navigate", value=URL)
    for target in targets:
        b.add("click", target=target)
        b.add("navigated", url=f"{URL}#id=2")  # the click opened something
    model = map_trace(b.trace(), lang="en").model
    return model.steps[-1].model_dump(by_alias=True, exclude_none=True, mode="json")


def test_a_record_picked_by_its_only_value() -> None:
    """The rest of the row is empty, and the clicked name still picks the record."""
    cell = in_row(tag="td", role="cell", name="Ceny C001", text="Ceny C001",
                  column="Pricelist Name", row=ROW, css=ROW_CSS.format(3))  # fmt: skip
    step = last_step(cell)
    assert step["within"]["where"] == {"Pricelist Name": "$inputs.pricelist_name"}
    assert step["target"] == [{"role": "cell", "column": "Pricelist Name"}]


def test_a_button_alone_in_its_row_is_a_command() -> None:
    alone = RowContext(cells={"Apply on": "Add a line"})
    add = in_row(tag="a", role="button", name="Add a line", text="Add a line", column="Apply on",
                 row=alone, css=ROW_CSS.format(1) + " > a")  # fmt: skip
    step = last_step(add)
    assert "within" not in step
    assert step["target"] == [{"role": "button", "name": "Add a line"}, {"text": "Add a line"}]


def test_a_place_in_a_row_is_kept_when_nothing_else_finds_the_element() -> None:
    """A path through row numbers is fragile, but a step without any way to find its
    element would not even make a model."""
    empty = in_row(tag="td", role="cell", column="Country Groups", row=ROW, css=ROW_CSS.format(4))
    step = last_step(empty)
    assert step["target"] == [{"css": ROW_CSS.format(4)}]


def test_a_help_mark_is_not_part_of_a_fields_name() -> None:
    b = Builder()
    b.add("fill", target=field("Product?"), value="48212-B")
    b.add("fill", target=field("Is it new ?"), value="yes")
    assert [a.field_name for a in normalize(b.trace()).acts] == ["Product", "Is it new ?"]


def test_rows_of_two_lists_with_a_column_of_one_name_pick_two_values() -> None:
    """Two lists of values with a „Value” column (a price list's name, then its currency):
    two values of the record, not the first one twice (the currency's row was looked for by
    the price list's name)."""
    b = Builder()
    b.add("navigate", value=URL)
    for table, value in (("Price Lists", "Wholesale"), ("Currencies", "USD")):
        row = RowContext(table=table, cells={"Value": value}, index=1)
        b.add("click", target=in_row(tag="java:table cell", role="cell", name=value, text=value,
                                     column="Value", row=row))  # fmt: skip
        b.add("navigated", url=f"{URL}#{table}")
    model = map_trace(b.trace(), lang="en").model
    picks = [s.within.where for s in model.steps if s.within is not None]
    assert picks == [{"Value": "$inputs.value"}, {"Value": "$inputs.currencies_value"}]
    assert {k: v.example for k, v in model.inputs.items()} == {
        "value": "Wholesale",
        "currencies_value": "USD",
    }
