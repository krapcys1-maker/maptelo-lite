"""Two fields with one label (benchmark g013, dup_label): „Rabat” in the part „Zgłoszenie” and
„Rabat” in „Realizacja”, typed from the sheet's columns Rabat and Limit. They are two fields of
one record, not the lines of an order: each gets its own input, and nothing is done per line."""

from __future__ import annotations

from pathlib import Path

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo
from maptelo.trace.schema import DataRef, RowContext
from tests.mapping.test_many_apps import ERP, Recording, found_by_its_words

URL = f"{ERP}/delegacje/1"
FORM = """- main:
  - heading "Delegacja DE/2026/0001" [level=1]
  - group "Zgłoszenie":
    - textbox "Rabat"
  - group "Realizacja":
    - textbox "Rabat"
  - button "Wystaw"
"""


def rabat(key: str) -> ElementInfo:
    info = ElementInfo(
        tag="input", role="textbox", name="Rabat", label="Rabat", field=key, id=f"g013-{key}"
    )
    return found_by_its_words(info)


def recording(folder: Path, sheet: str, typed: tuple[str, str]) -> Recording:
    (folder / "delegacje.csv").write_text(sheet, encoding="utf-8")
    r = Recording()
    form = r.state(URL, FORM)
    r.add("navigate", URL, value=URL, state_after=form)
    r.add("fill", URL, target=rabat("f1"), value=typed[0], state_before=form)
    r.add("fill", URL, target=rabat("f2"), value=typed[1], state_before=form)
    save = found_by_its_words(ElementInfo(tag="button", role="button", name="Wystaw"))
    r.add("click", URL, target=save, state_before=form, state_after=form, sent=["POST /d"])
    return r


def test_two_fields_of_one_label_typed_from_two_columns_are_two_inputs(tmp_path: Path) -> None:
    sheet = "Numer delegacji;Rabat;Limit\nDE/2026/0001;32000.00;20028.74\n"
    r = recording(tmp_path, sheet, ("32000.00", "20028.74"))
    model = map_trace(r.trace(tmp_path / "trace.jsonl", DataRef(file="delegacje.csv"))).model
    fills = [s for s in model.steps if s.action.value == "fill"]
    assert [s.value for s in fills] == ["$inputs.rabat", "$inputs.limit"]
    assert not any(s.per_line for s in model.steps)
    assert model.inputs["limit"].description == "Rabat (Limit)"
    assert not any(spec.per_line for spec in model.inputs.values())


def test_the_same_label_typed_from_one_column_is_still_the_lines_of_a_record(
    tmp_path: Path,
) -> None:
    """Values of one column, in two rows of the sheet: the lines of one record, as before."""
    sheet = "Numer delegacji;Rabat\nDE/2026/0001;32000.00\nDE/2026/0001;8000.00\n"
    r = recording(tmp_path, sheet, ("32000.00", "8000.00"))
    model = map_trace(r.trace(tmp_path / "trace.jsonl", DataRef(file="delegacje.csv"))).model
    fills = [s for s in model.steps if s.action.value == "fill"]
    assert [s.value for s in fills] == ["$inputs.rabat"]
    assert fills[0].per_line


def test_two_lookup_prefixes_from_two_columns_are_not_lines(tmp_path: Path) -> None:
    sheet = "Numer delegacji;Indeks 1;Indeks 2\nDE/2026/0001;12187-H;42710-E\n"
    r = recording(tmp_path, sheet, ("12187%", "42710%"))
    model = map_trace(r.trace(tmp_path / "trace.jsonl", DataRef(file="delegacje.csv"))).model
    fills = [s for s in model.steps if s.action.value == "fill"]
    assert len(fills) == 2
    assert not any(s.per_line for s in model.steps)
    assert [model.inputs[s.value.removeprefix("$inputs.")].column for s in fills] == [
        "Indeks 1",
        "Indeks 2",
    ]


def test_two_selected_rows_keep_their_distinct_sheet_columns(tmp_path: Path) -> None:
    (tmp_path / "items.csv").write_text("Indeks 1;Indeks 2\nA-123;B-456\n", encoding="utf-8")
    r = Recording()
    state = r.state(URL, '- table "Products"\n- button "Add"\n')
    for sku in ("A-123", "B-456"):
        row = found_by_its_words(
            ElementInfo(
                tag="td",
                role="cell",
                name=sku,
                column="Indeks",
                row=RowContext(table="Products", cells={"Indeks": sku}),
            )
        )
        r.add("click", URL, target=row, state_before=state)
        button = found_by_its_words(ElementInfo(tag="button", role="button", name="Add"))
        r.add("click", URL, target=button, state_before=state)
    model = map_trace(r.trace(tmp_path / "trace.jsonl", DataRef(file="items.csv"))).model
    selections = [s for s in model.steps if s.within]
    assert len(selections) == 2
    assert [
        model.inputs[s.within.where["Indeks"].removeprefix("$inputs.")].column for s in selections
    ] == ["Indeks 1", "Indeks 2"]
    assert not any(s.per_line for s in model.steps)


def test_a_record_value_inside_a_links_name_does_not_name_the_link(tmp_path: Path) -> None:
    """The issuer chosen in the filter (K0009), then „Podgląd SBI/K0009/2026/0022” clicked in its
    row: the link is its row's own, not one named by the issuer column (benchmark M5: the step
    became a click on a link named „K0017”, which several rows showed, and every record failed)."""
    (tmp_path / "sieci.csv").write_text("Wystawca\nK0009\n", encoding="utf-8")
    r = Recording()
    page = f"{ERP}/dokumenty"
    shown = r.state(
        page,
        '- combobox "Wystawca"\n- table "Faktury samofakturowania"\n'
        '- link "Podgląd SBI/K0009/2026/0022"\n',
    )
    r.add("navigate", page, value=page, state_after=shown)
    choice = found_by_its_words(ElementInfo(tag="select", role="combobox", name="Wystawca"))
    r.add("select", page, target=choice, value="K0009", state_before=shown)
    link = found_by_its_words(
        ElementInfo(
            tag="a",
            role="link",
            name="Podgląd SBI/K0009/2026/0022",
            row=RowContext(
                table="Faktury samofakturowania", cells={"Numer": "SBI/K0009/2026/0022"}
            ),
        )
    )
    r.add("click", page, target=link, state_before=shown)
    model = map_trace(r.trace(tmp_path / "trace.jsonl", DataRef(file="sieci.csv"))).model
    names = [loc.name for s in model.steps if s.action.value == "click" for loc in s.target or []]
    assert "{inputs.wystawca}" not in names
