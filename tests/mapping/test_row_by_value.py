"""The row a person picks is named by what it is, not by what it says: an amount from the
sheet („Stara cena” 11,06) stands in the active price version's row, yet the version is picked
because it is the active one (benchmark p01, after p13's row named by the sheet's employee)."""

from __future__ import annotations

from pathlib import Path

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo, Trace
from maptelo.trace.schema import DataRef, RowContext
from tests.mapping.test_many_apps import ERP, Recording, field, found_by_its_words

PRICES = f"{ERP}/cenniki"
VERSIONS = """- main:
  - heading "Cenniki klientów" [level=1]
  - textbox "Produkt"
  - table "Wersje ceny":
    - rowgroup:
      - row "Od Cena Status":
        - columnheader "Od"
        - columnheader "Cena"
        - columnheader "Status"
        - columnheader
    - rowgroup:
      - row "2026-01-02 10,50 Wygasła Wybierz":
        - cell "2026-01-02"
        - cell "10,50"
        - cell "Wygasła"
        - cell "Wybierz":
          - link "Wybierz"
      - row "2026-06-01 11,06 Aktywna Wybierz":
        - cell "2026-06-01"
        - cell "11,06"
        - cell "Aktywna"
        - cell "Wybierz":
          - link "Wybierz"
"""
SHEET = "Produkt;Stara cena;Nowa cena\n48212-B;11,06;12,40\n"


def picked(folder: Path) -> Trace:
    r = Recording()
    screen = r.state(PRICES, VERSIONS)
    r.add("navigate", PRICES, value=PRICES, state_after=screen)
    r.add("fill", PRICES, target=field("Produkt"), value="48212-B", state_before=screen)
    row = RowContext(
        table="Wersje ceny",
        cells={"Od": "2026-06-01", "Cena": "11,06", "Status": "Aktywna", "#4": "Wybierz"},
        index=1,
    )
    link = found_by_its_words(
        ElementInfo(tag="a", role="link", name="Wybierz", text="Wybierz", row=row, column="#4")
    )
    r.add("click", PRICES, target=link, state_before=screen, state_after=screen)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ceny.csv").write_text(SHEET, "utf-8")
    return r.trace(folder / "trace.jsonl", DataRef(file="ceny.csv"), name="ceny")


def test_the_active_version_is_picked_by_its_status_not_by_its_price(tmp_path: Path) -> None:
    model = map_trace(picked(tmp_path)).model
    pick = next(s for s in model.steps if s.within is not None)
    assert pick.within is not None
    assert pick.within.where == {"Status": "Aktywna"}
    assert not any(spec.column == "Stara cena" for spec in model.inputs.values())
