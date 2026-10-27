"""A new line no value of the record names yet, whose other cells hold only what the form wrote
by itself (Oracle Forms' Grouping Number -1 as the cursor came): named by those cells and its
own empty field, when they name one row (benchmark D08: the second qualifier's row)."""

from __future__ import annotations

from maptelo.mapping.build import _named_by_its_defaults

ROWS = [
    {"Grouping Number": "-1", "Qualifier Context": "Customer"},
    {"Grouping Number": "-1", "Qualifier Context": ""},
    {"Grouping Number": "", "Qualifier Context": ""},
    {"Grouping Number": "", "Qualifier Context": ""},
]


def test_the_row_the_form_wrote_into_is_named_by_it() -> None:
    cells = {"Grouping Number": "-1", "Qualifier Context": ""}
    assert _named_by_its_defaults(cells, "Qualifier Context", ROWS) == {
        "where": {"Grouping Number": "-1", "Qualifier Context": None}
    }


def test_cells_that_fit_several_rows_name_none() -> None:
    rows = [*ROWS[1:2], *ROWS[1:2]]
    cells = {"Grouping Number": "-1", "Qualifier Context": ""}
    assert _named_by_its_defaults(cells, "Qualifier Context", rows) is None


def test_an_amount_or_a_date_is_no_default_that_names_a_row() -> None:
    rows = [{"Start Date": "25-OCT-2026", "Value": ""}, {"Start Date": "", "Value": ""}]
    assert _named_by_its_defaults({"Start Date": "25-OCT-2026", "Value": ""}, "Value", rows) is None
