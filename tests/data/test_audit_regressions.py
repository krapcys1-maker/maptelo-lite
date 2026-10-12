from io import BytesIO

import pytest
from openpyxl import Workbook

from maptelo.data import read_table, write_results
from maptelo.data.tables import TableError
from maptelo.studio.workspace import Workspace


def test_multiline_csv_survives_repeated_results_export(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text('id,note\nA,"first\nsecond"\n', encoding="utf-8")
    table = read_table(path)
    assert table.rows[0]["note"] == "first\nsecond"
    first = write_results(table, {1: {"outcome": "VERIFIED", "message": "ok"}}, tmp_path / "one")
    second = write_results(
        read_table(first), {1: {"outcome": "REJECTED", "message": "bad"}}, tmp_path / "two"
    )
    import csv

    with second.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0].count("Maptelo outcome") == 1
    assert rows[1][1] == "first\nsecond"
    assert rows[1][2] == "REJECTED"


def test_excel_identifier_display_and_upload_validation(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.append(["id", "value"])
    sheet.append([123, "A"])
    sheet["A2"].number_format = "000000"
    data = BytesIO()
    book.save(data)
    workspace = Workspace(tmp_path)
    first = workspace.keep_sheet("codes.xlsx", data.getvalue())
    second = workspace.keep_sheet("codes.xlsx", data.getvalue())
    assert first != second
    assert read_table(first).rows[0]["id"] == "000123"
    with pytest.raises(TableError):
        workspace.keep_sheet("broken.xlsx", b"PK")
    assert len(list(workspace.sheets.glob("*"))) == 2
