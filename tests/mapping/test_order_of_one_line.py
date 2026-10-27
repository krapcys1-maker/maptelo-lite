"""An order recorded with one line (benchmark P02, the recording 01-pozycji-1, 19.10): the
sheet the person worked from has orders of several rows, a row a line, but nothing repeated in
the recording, so its map does a row at a time. Whether rows are one record, one recording
cannot show, and the sheet cannot either (a customer's code repeats in the rows of separate
records too, P16): Maptelo Lite asks, and says how to show it. A recording of two lines maps to
an order at a time."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from maptelo.export.ai_brief import open_questions
from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo, Trace
from maptelo.trace.schema import DataRef
from tests.mapping.test_many_apps import ERP, Recording, field, found_by_its_words

NEW = f"{ERP}/zamowienia/nowe"
LISTED = f"{ERP}/zamowienia"
HEAD = "Klient;Nr zamówienia klienta;Data dostawy;Produkt;Ilość\n"
RECORDED = [  # the sheet the person recorded from: the first order has one line, the next two
    ("K0010", "ZK-101001", "2026-10-18", "43871-B", "11"),
    ("K0017", "ZK-101002", "2026-10-19", "98460-F", "12"),
    ("K0017", "ZK-101002", "2026-10-19", "49043-C", "22"),
]


def form(lines: int) -> str:
    rows = "\n".join(f'    - row "{n}"' for n in range(lines))
    return (
        '- main:\n  - heading "Nowe zamówienie" [level=1]\n  - combobox "Klient"\n'
        '  - textbox "Numer referencyjny klienta"\n  - textbox "Data dostawy"\n'
        '  - textbox "Produkt"\n  - textbox "Ilość"\n  - button "Dodaj pozycję"\n'
        f'  - table "Pozycje zamówienia":\n{rows}\n  - button "Zapisz zamówienie"\n'
    )


def button(name: str) -> ElementInfo:
    return found_by_its_words(ElementInfo(tag="button", role="button", name=name))


def sheet(folder: Path, rows: Sequence[tuple[str, ...]]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "zamowienia.csv"
    path.write_text(HEAD + "".join(";".join(row) + "\n" for row in rows), encoding="utf-8")
    return path


def order(folder: Path, lines: int, name: str = "01-pozycji-1") -> Trace:
    """The person types an order of ``lines`` lines (one: the first order of the sheet; two:
    the second), adding each line under the order, and saves it."""
    rows = [RECORDED[0]] if lines == 1 else RECORDED[1 : 1 + lines]
    customer, number, day = rows[0][:3]
    r = Recording()
    empty = r.state(NEW, form(0))
    r.add("navigate", NEW, value=NEW, state_after=empty)
    choice = found_by_its_words(ElementInfo(tag="select", role="combobox", name="Klient"))
    r.add("select", NEW, target=choice, value=customer, state_before=empty)
    r.add("fill", NEW, target=field("Numer referencyjny klienta"), value=number, state_before=empty)
    r.add("fill", NEW, target=field("Data dostawy"), value=day, state_before=empty)
    before = empty
    for index, row in enumerate(rows, start=1):
        r.add("fill", NEW, target=field("Produkt"), value=row[3], state_before=before)
        r.add("fill", NEW, target=field("Ilość"), value=row[4], state_before=before)
        after = r.state(NEW, form(index))
        r.add("click", NEW, target=button("Dodaj pozycję"), state_before=before,
              state_after=after, sent=["POST /zamowienia/nowe/pozycje"])  # fmt: skip
        before = after
    saved = r.state(LISTED, '- main:\n  - table "Zamówienia sprzedaży"\n')
    r.add("click", NEW, target=button("Zapisz zamówienie"), state_before=before,
          state_after=saved, sent=["POST /zamowienia"])  # fmt: skip
    r.add("navigated", LISTED, state_before=before, state_after=saved)
    place = folder / name
    sheet(place, RECORDED)
    return r.trace(place / "trace.jsonl", DataRef(file="zamowienia.csv"), name=name)


def test_the_map_of_one_line_does_a_row_at_a_time(tmp_path: Path) -> None:
    model = map_trace(order(tmp_path, lines=1)).model
    assert not any(step.per_line for step in model.steps)
    assert model.records is not None
    assert not model.records.one_run_per
    assert {spec.column for spec in model.inputs.values()} == set(HEAD.strip().split(";"))


def test_the_map_of_two_lines_does_an_order_at_a_time(tmp_path: Path) -> None:
    model = map_trace(order(tmp_path, lines=2, name="02-pozycji-2")).model
    assert model.records is not None
    assert model.records.one_run_per == ["Klient", "Nr zamówienia klienta", "Data dostawy"]
    lines = {spec.column for spec in model.inputs.values() if spec.per_line}
    assert lines == {"Produkt", "Ilość"}


def test_the_brief_asks_whether_a_record_is_several_rows(tmp_path: Path) -> None:
    """Maptelo Lite maps one recording and joins none: a map that does a row at a time asks
    what makes rows one record, and how to show it (a recording of several rows, or the
    person's words); until then rows the check cannot tell apart are not run. The map of a
    recording of two lines knows it."""
    one = map_trace(order(tmp_path, lines=1)).model
    asked = [q for q in open_questions(one, "pl", one_recording=True) if "wiersz arkusza" in q]
    assert asked == [
        "Mapa robi każdy wiersz arkusza osobno, bo nagranie pokazało rekord z jednego wiersza. "
        "Czy rekord bywa kilkoma wierszami (np. pozycje jednego zamówienia)? Jeśli tak, nagraj "
        "przypadek z kilkoma wierszami (mapa z takiego nagrania powtarza pozycje) albo opisz "
        "słowami, po których kolumnach poznać wiersze jednego rekordu i które kroki powtarza się "
        "dla każdej pozycji. Do tego czasu nie wykonuj wierszy, których sprawdzenie wyniku nie "
        "odróżnia od siebie."
    ]
    english = open_questions(one, "en", one_recording=True)
    assert any(q.startswith("The map does each row of the sheet on its own") for q in english)
    assert not [q for q in open_questions(one, "pl") if "wiersz arkusza" in q]  # several
    two = map_trace(order(tmp_path / "two", lines=2, name="02-pozycji-2")).model
    assert not [q for q in open_questions(two, "pl", one_recording=True) if "wiersz arkusza" in q]
