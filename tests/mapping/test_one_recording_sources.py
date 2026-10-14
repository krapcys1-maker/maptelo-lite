"""A map of one recording made with its sheet says where each value comes from, as the model of
several recordings does: the column, and how the screen wants it typed (benchmark M2: the
customer searched for as „K0010%”, the date typed „01-LIS-2026”). Without it Maptelo Lite's AI
brief said „not known” for every value."""

from __future__ import annotations

from pathlib import Path

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo
from maptelo.trace.schema import DataRef
from tests.mapping.test_many_apps import ERP, Recording, found_by_its_words

URL = f"{ERP}/cenniki"
FORM = """- main:
  - textbox "Nazwa"
  - textbox "Od"
  - textbox "Uwagi"
  - button "Znajdź"
"""


def recording(folder: Path) -> Recording:
    (folder / "ceny.csv").write_text(
        "Klient;Obowiązuje od;Uwagi\nK0010;2026-11-01;pilne\nK0018;2026-12-01;pilne\n", "utf-8"
    )
    r = Recording()
    form = r.state(URL, FORM)
    r.add("navigate", URL, value=URL, state_after=form)
    for label, typed in (("Nazwa", "K0010%"), ("Od", "01-LIS-2026"), ("Uwagi", "pilne")):
        box = found_by_its_words(ElementInfo(tag="input", role="textbox", name=label, label=label))
        r.add("fill", URL, target=box, value=typed, state_before=form)
    find = found_by_its_words(ElementInfo(tag="button", role="button", name="Znajdź"))
    r.add("click", URL, target=find, state_before=form, state_after=form)
    return r


def test_a_map_of_one_recording_takes_its_values_from_the_sheets_columns(tmp_path: Path) -> None:
    trace = recording(tmp_path).trace(tmp_path / "trace.jsonl", DataRef(file="ceny.csv"), "r1")
    result = map_trace(trace)
    inputs = result.model.inputs
    by_label = {spec.description: spec for spec in inputs.values()}
    assert by_label["Nazwa"].column == "Klient"
    assert by_label["Nazwa"].typed_as == "{}%"
    assert by_label["Od"].column == "Obowiązuje od"
    assert by_label["Od"].typed_as == "DD-MON-RRRR"
    assert by_label["Od"].type.value == "date"
    assert by_label["Uwagi"].column == "Uwagi"  # in the record's row (the others' too)
    assert result.model.records is not None
    assert result.model.records.description == "ceny.csv"
