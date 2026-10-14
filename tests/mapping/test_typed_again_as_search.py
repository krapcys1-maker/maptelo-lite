"""The item typed whole in query mode, then into the new line as a search („26386%”, benchmark M2):
the second is typed so, an input of its own (the sheet's item, then %), not the whole item that
opens no list of values."""

from __future__ import annotations

from pathlib import Path

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo
from maptelo.trace.schema import DataRef
from tests.mapping.test_many_apps import ERP, Recording, found_by_its_words

URL = f"{ERP}/cennik"
FORM = """- main:
  - textbox "Indeks"
  - button "Wykonaj zapytanie"
  - button "Zapisz"
"""


def test_the_item_typed_again_as_a_search_is_typed_so(tmp_path: Path) -> None:
    (tmp_path / "ceny.csv").write_text("Indeks;Cena\n26386-F;6.04\n31830-D;5.30\n", "utf-8")
    r = Recording()
    form = r.state(URL, FORM)
    r.add("navigate", URL, value=URL, state_after=form)
    box = found_by_its_words(
        ElementInfo(tag="input", role="textbox", name="Indeks", label="Indeks")
    )
    r.add("fill", URL, target=box, value="26386-F", state_before=form)
    query = found_by_its_words(ElementInfo(tag="button", role="button", name="Wykonaj zapytanie"))
    r.add("click", URL, target=query, state_before=form, state_after=form)
    r.add("fill", URL, target=box, value="26386%", state_before=form)
    save = found_by_its_words(ElementInfo(tag="button", role="button", name="Zapisz"))
    r.add("click", URL, target=save, state_before=form, state_after=form)
    model = map_trace(r.trace(tmp_path / "trace.jsonl", DataRef(file="ceny.csv"), "r1")).model
    first, second = [s.value for s in model.steps if s.action.value == "fill"]
    assert first != second
    whole = model.inputs[str(first).removeprefix("$inputs.")]
    search = model.inputs[str(second).removeprefix("$inputs.")]
    assert (whole.column, whole.typed_as) == ("Indeks", None)
    assert (search.column, search.typed_as) == ("Indeks", "{}%")
