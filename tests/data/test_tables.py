"""Tables people work from: workbooks and CSV files, read as rows of text."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from maptelo.data import TableError, cell_text, read_table


def workbook(path: Path) -> Path:
    book = Workbook()
    notes = book.active
    assert notes is not None
    notes.title = "Notes"
    notes.append(["This sheet is not the price list"])
    prices = book.create_sheet("Ceny")
    prices.append([])  # people often leave a row above the headers
    prices.append(["Klient", "CPN", "Nowa cena", "Od", "Uwagi", None])
    prices.append(["C001", "48212-B", 135.0, datetime(2026, 12, 1), "pilne"])
    prices.append([None, None, None, None, None])  # an empty row is not a record
    prices.append(["C002", "51001-A", 47.5, datetime(2026, 12, 1, 8, 30), None])
    book.save(path)
    return path


def test_cells_read_as_people_see_them() -> None:
    assert cell_text(135.0) == "135"
    assert cell_text(129.9) == "129.9"
    assert cell_text(datetime(2026, 12, 1)) == "2026-12-01"
    assert cell_text(datetime(2026, 12, 1, 8, 30)) == "2026-12-01 08:30:00"
    assert cell_text(date(2027, 1, 15)) == "2027-01-15"
    assert (cell_text(True), cell_text(None), cell_text("  C001 ")) == ("true", "", "C001")


def test_a_sheet_of_a_workbook(tmp_path: Path) -> None:
    table = read_table(workbook(tmp_path / "ceny.xlsx"), "Ceny")
    assert table.source == "ceny.xlsx, sheet Ceny"
    assert table.headers == ["Klient", "CPN", "Nowa cena", "Od", "Uwagi"]
    assert table.rows == [
        {"Klient": "C001", "CPN": "48212-B", "Nowa cena": "135", "Od": "2026-12-01",
         "Uwagi": "pilne"},
        {"Klient": "C002", "CPN": "51001-A", "Nowa cena": "47.5", "Od": "2026-12-01 08:30:00",
         "Uwagi": ""},
    ]  # fmt: skip
    assert read_table(tmp_path / "ceny.xlsx").headers == ["This sheet is not the price list"]


def test_wrong_sheets_and_files_are_named(tmp_path: Path) -> None:
    with pytest.raises(TableError, match=r"no sheet 'Prices' \(sheets: Notes, Ceny\)"):
        read_table(workbook(tmp_path / "ceny.xlsx"), "Prices")
    csv = tmp_path / "ceny.csv"
    csv.write_text("customer;cpn\nC001;48212-B\n;\n", encoding="utf-8")
    assert read_table(csv).rows == [{"customer": "C001", "cpn": "48212-B"}]
    with pytest.raises(TableError, match="not a workbook"):
        read_table(csv, "Ceny")
    broken = tmp_path / "broken.xlsx"
    broken.write_text("not a workbook", encoding="utf-8")
    with pytest.raises(TableError, match="cannot be read as a workbook"):
        read_table(broken)
