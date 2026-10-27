"""A field typed in some lines of an order only (a line's own warehouse, typed for the lines the
sheet names one for): the lines are one block done for each line all the same, the field done in
a line when the sheet's column has its value. An order of twelve lines with it in two of them was
mapped as twelve copies of the line's steps (benchmark D09)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from maptelo.mapping import map_trace
from maptelo.trace import Trace
from maptelo.trace.schema import DataRef
from tests.mapping.test_many_apps import ERP, Recording, field

URL = f"{ERP}/zamowienia/nowe"
HEAD = "Nr zamówienia;Produkt;Ilość;Magazyn\n"
FORM = (
    '- main:\n  - textbox "Numer zamówienia"\n  - textbox "Produkt"\n  - textbox "Ilość"\n'
    '  - textbox "Magazyn"\n  - button "Zapisz"\n'
)
ROWS = [
    ("ZK-4410", "26386-F", "40", ""),
    ("ZK-4410", "48212-B", "15", "MAG-GDA"),
    ("ZK-4410", "31830-D", "25", ""),
    ("ZK-4410", "43871-B", "10", ""),
    ("ZK-4410", "98460-F", "60", "MAG-GDA"),
]


def order(folder: Path, rows: Sequence[tuple[str, ...]], typed: set[int]) -> Trace:
    """The person types the order's number, then each line, and the warehouse in the lines
    ``typed`` (by their index); the sheet has ``rows``."""
    r = Recording()
    form = r.state(URL, FORM)
    r.add("navigate", URL, value=URL, state_after=form)
    r.add("fill", URL, target=field("Numer zamówienia"), value=rows[0][0], state_before=form)
    for index, (_, item, qty, warehouse) in enumerate(rows):
        r.add("fill", URL, target=field("Produkt"), value=item, state_before=form)
        r.add("fill", URL, target=field("Ilość"), value=qty, state_before=form)
        if index in typed:
            r.add("fill", URL, target=field("Magazyn"), value=warehouse or "MAG-WAW",
                  state_before=form)  # fmt: skip
    r.add("click", URL, target=field("Zapisz"), state_before=form, state_after=form,
          sent=["POST /zamowienia"])  # fmt: skip
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "zamowienia.csv").write_text(
        HEAD + "".join(";".join(row) + "\n" for row in rows), encoding="utf-8"
    )
    return r.trace(folder / "trace.jsonl", DataRef(file="zamowienia.csv"), name="01")


def test_a_field_of_some_lines_is_done_when_the_sheet_names_its_value(tmp_path: Path) -> None:
    model = map_trace(order(tmp_path, ROWS, typed={1, 4})).model
    fills = [s for s in model.steps if s.action.value == "fill"]
    assert [s.target[0].name for s in fills if s.target] == [
        "Numer zamówienia", "Produkt", "Ilość", "Magazyn",
    ]  # fmt: skip
    warehouse = fills[-1]
    assert all(s.per_line for s in fills[1:])
    assert warehouse.when is not None
    assert warehouse.when.value is not None
    assert warehouse.when.value.of == warehouse.value
    assert warehouse.when.value.empty is False
    name = str(warehouse.value).removeprefix("$inputs.")
    assert model.inputs[name].per_line
    assert model.inputs[name].column == "Magazyn"
    assert not model.inputs[name].required
    assert model.records is not None
    assert model.records.one_run_per == ["Nr zamówienia"]


def test_a_field_typed_where_the_sheet_says_nothing_of_it_leaves_the_lines_as_done(
    tmp_path: Path,
) -> None:
    """The warehouse typed in the third line, for which the sheet names none: the sheet does
    not tell when the field is typed, so no rule is made up."""
    model = map_trace(order(tmp_path, ROWS, typed={1, 2, 4})).model
    assert not any(s.per_line for s in model.steps)
