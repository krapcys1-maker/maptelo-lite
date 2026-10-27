"""A value typed on screen and the cell of the sheet it came from, in the forms people and
programs write them (a CSV file saved out of Excel, a program's own masks): any case and
spaces, a number Excel saved as 604217359.0, a date as 01.11.2026, 2026-11-01,
01/November/2026, Oracle's 01-NOV-2026 or Excel's number of the day, words around the value
(„Account 604217359”) and the part of it after a separator (5510 of „CENNIK_ZK_5510”)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from maptelo.data.tables import Table, read_table
from maptelo.dates import EXCEL_SERIAL, ORACLE_MASK, excel_day, written_day
from maptelo.mapping.sources import Origin, bind, readings, trace_origins, written_dates
from maptelo.model.schema import InputSpec


def origins(cell: str, typed: str) -> dict[str, Origin]:
    table = Table(["Kolumna", "Inna"], [{"Kolumna": cell, "Inna": "x"}], "t")
    return trace_origins([{"wartosc": typed}], [table]).origins


@pytest.mark.parametrize(
    ("cell", "typed", "typed_as", "written_as"),
    [
        ("2026-11-01", "01.11.2026", "%d.%m.%Y", None),
        ("2026-11-01", "01-NOV-2026", ORACLE_MASK, None),
        ("2026-11-01", "01/November/2026", "%d/%B/%Y", None),
        ("01.11.2026", "2026-11-01", None, "%d.%m.%Y"),
        ("01.11.2026", "01-NOV-2026", ORACLE_MASK, "%d.%m.%Y"),
        ("01/November/2026", "01.11.2026", "%d.%m.%Y", "%d/%B/%Y"),
        ("01-NOV-2026", "01.11.2026", "%d.%m.%Y", ORACLE_MASK),
        ("46327", "01-NOV-2026", ORACLE_MASK, EXCEL_SERIAL),
        ("46327", "2026-11-01", None, EXCEL_SERIAL),
    ],
)
def test_a_typed_date_is_the_sheets_date(
    cell: str, typed: str, typed_as: str | None, written_as: str | None
) -> None:
    assert origins(cell, typed) == {"wartosc": Origin("Kolumna", "date", typed_as, written_as)}


def test_a_date_typed_as_the_sheet_writes_it_is_a_date_not_a_text() -> None:
    """„15.01.2027” in both: once a text, a date and a phone number, so no column at all."""
    found = origins("15.01.2027", "15.01.2027")
    assert found == {"wartosc": Origin("Kolumna", "date", "%d.%m.%Y", "%d.%m.%Y")}


def test_excels_number_of_the_day() -> None:
    assert excel_day("46327") == date(2026, 11, 1)
    assert excel_day("46327.0") == date(2026, 11, 1)
    assert excel_day("604217359") is None  # an account
    assert excel_day("12") is None  # a count
    assert written_day("46327", EXCEL_SERIAL) == date(2026, 11, 1)
    assert written_day("01-LIS-2026", "DD-MON-RRRR") == date(2026, 11, 1)


def test_text_in_any_case_and_spaces() -> None:
    assert origins("Cennik Hurt K0010", "  cennik hurt  K0010 ") == {
        "wartosc": Origin("Kolumna", "text")
    }


def test_a_number_excel_saved_with_its_point_zero(tmp_path: Path) -> None:
    sheet = tmp_path / "konta.csv"
    sheet.write_text("Konto;Cena\n604217359.0;6.0\n", "utf-8")
    assert read_table(sheet).rows == [{"Konto": "604217359", "Cena": "6"}]
    assert ("number", "0.00") in readings("6", "6.00")  # an amount stays an amount


def test_words_around_the_value() -> None:
    assert origins("604217359", "Account 604217359") == {
        "wartosc": Origin("Kolumna", "text", "Account {}")
    }
    assert origins("604217359", "Account 1604217359") == {}  # a part of another number
    assert origins("2026", "Account 2026") == {}  # four digits stand anywhere


def test_the_part_after_a_separator() -> None:
    found = origins("CENNIK_ZK_5510", "5510")
    assert found == {"wartosc": Origin("Kolumna", "part", "_ZK_")}
    spec = {"type": "string", "description": "PO", "example": "5510"}
    bind(spec, found["wartosc"], {"Kolumna": "CENNIK_ZK_5510"})
    assert spec == {**spec, "column": "Kolumna", "taken_after": "_ZK_"}
    held = InputSpec.model_validate(spec)
    assert held.coerce("HURT_ZK_5599") == "5599"
    assert held.coerce("5599") == "5599"  # given cut already


def test_a_last_word_or_a_short_end_is_no_part() -> None:
    assert origins("Contract prices K0010 2026", "2026") == {}  # after a space only
    assert written_dates("Ceny", "Ceny") == set()
    assert origins("CENNIK_ZK_AB", "AB") == {}


def test_the_header_of_a_record_of_two_rows() -> None:
    """Only the header typed (the lines chosen from a list): both rows of the record hold it the
    same way; before, two rows fitting as well left every value without its column."""
    rows = [
        {"Nazwa cennika": "WRK_ZK_5510", "Konto": "604217359", "Indeks": item}
        for item in ("26386-F", "31830-D")
    ]
    table = Table(list(rows[0]), rows, "t")
    typed = {"nazwa": "WRK_ZK_5510", "konto": "Account 604217359", "kontekst": "Customer"}
    found = trace_origins([typed], [table], together=True).origins
    assert found == {
        "nazwa": Origin("Nazwa cennika", "text"),
        "konto": Origin("Konto", "text", "Account {}"),
    }
    assert trace_origins([typed], [table]).origins == {}  # recordings together: which row?
    other = [{"Status": "Tak", "Ilość": "1"}, {"Status": "Tak", "Ilość": "1"}]
    plain = Table(["Status", "Ilość"], other, "t")
    nothing = trace_origins([{"a": "Tak", "b": "1"}], [plain], together=True)
    assert nothing.origins == {}  # nothing names a record there: still no column by chance


def test_a_value_whole_in_one_column_and_the_end_of_another() -> None:
    table = Table(["Nazwa", "Rok"], [{"Nazwa": "WRK-K0010-2026", "Rok": "2026"}], "t")
    found = trace_origins([{"rok": "2026", "nazwa": "WRK-K0010-2026"}], [table])
    assert found.origins["rok"] == Origin("Rok", "text")


def test_the_sheets_way_of_writing_a_date_is_read_back() -> None:
    spec = InputSpec.model_validate(
        {"type": "date", "written_as": EXCEL_SERIAL, "typed_as": ORACLE_MASK}
    )
    assert spec.coerce("46327") == date(2026, 11, 1)
    assert spec.on_screen(date(2026, 11, 1)) == "01-NOV-2026"
    named = InputSpec.model_validate({"type": "date", "written_as": "%d/%B/%Y"})
    assert named.coerce("01/November/2026") == date(2026, 11, 1)
    with pytest.raises(ValueError, match="written_as"):
        InputSpec.model_validate({"type": "date", "written_as": "excel days"})
    with pytest.raises(ValueError, match="taken_after"):
        InputSpec.model_validate({"type": "decimal", "taken_after": "_ZK_"})
