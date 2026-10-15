"""Where a typed value came from: the column of the sheet, and how it was typed."""

from __future__ import annotations

from maptelo.data import Table
from maptelo.mapping.sources import Origin, readings, trace_origins

HEADERS = ["Cennik", "Produkt", "Stara cena", "Cena", "Od", "Do"]


def row(*cells: str) -> dict[str, str]:
    return dict(zip(HEADERS, cells, strict=True))


SHEET = Table(
    HEADERS,
    [
        row("Ceny C001", "48212-B", "129.9", "140", "2027-01-15", "2027-03-03"),
        row("Ceny C003", "70010-A", "12.75", "13.2", "2027-02-01", "2027-02-01"),
        row("Ceny C002", "51001-A", "46.2", "47.5", "2027-03-03", ""),
    ],
    "ceny.xlsx, sheet Ceny",
)


def test_the_ways_a_cell_is_typed() -> None:
    assert readings("2027-01-15", "01/15/2027 00:00:00") == {("date", "%m/%d/%Y %H:%M:%S")}
    assert readings("2027-01-15", "15.01.2027") == {("date", "%d.%m.%Y")}
    assert readings("2027-01-15", "2027-01-15") == {("date", None)}
    assert readings("2027-03-03", "03/03/2027") == {("date", "%d/%m/%Y"), ("date", "%m/%d/%Y")}
    assert readings("140", "140.00") == {("number", "0.00")}
    assert readings("129.9", "129,90") == {("number", "0,00")}
    assert readings("C001", "c001") == {("text", None)}
    assert readings("140", "141.00") == set()
    assert readings("", "x") == set()


def test_columns_agreed_by_every_recording() -> None:
    typed = [
        {"pricelist": "Ceny C001", "product": "48212-B", "price": "140.00", "start": "01/15/2027"},
        {"pricelist": "Ceny C003", "product": "70010-A", "price": "13.20", "start": "02/01/2027"},
    ]
    found = trace_origins(typed, [SHEET, SHEET])
    assert found.origins == {
        "pricelist": Origin("Cennik"),
        "product": Origin("Produkt"),
        "price": Origin("Cena", "number", "0.00"),
        # 02/01/2027 alone could be February 1st or January 2nd; with 01/15/2027 it is clear
        "start": Origin("Od", "date", "%m/%d/%Y"),
    }
    assert found.support == 2


def test_a_value_in_two_columns_is_left_to_a_person() -> None:
    """On C003's row the start and end dates are the same: from that recording alone the
    date could be either column."""
    typed = [{"product": "70010-A", "price": "13.20", "start": "2027-02-01"}]
    found = trace_origins(typed, [SHEET])
    assert "start" not in found.origins
    assert [o.column for o in found.doubtful["start"]] == ["Do", "Od"]


def test_no_row_no_origin() -> None:
    nothing = trace_origins([{"price": "999.00", "code": "X"}], [SHEET])
    assert (nothing.origins, nothing.rows) == ({}, [None])
    two_rows = Table(HEADERS, [SHEET.rows[0], SHEET.rows[0]], "twice")
    assert trace_origins([{"product": "48212-B", "price": "140.00"}], [two_rows]).rows == [None]
    without = trace_origins([{"price": "140.00"}], [None])
    assert without.support == 0


RETURNS = Table(
    ["Zwrot", "Numer odbioru"],
    [
        {"Zwrot": "ZW/2026/002", "Numer odbioru": "ODB/2026/0001"},
        {"Zwrot": "ZW/2026/003", "Numer odbioru": "ODB/2026/0002"},
    ],
    "zwroty.xlsx, sheet Zwroty w drodze",
)


def test_a_document_number_alone_names_its_row() -> None:
    """A return received in the warehouse (benchmark p21): its number came from the
    sheet, the quantities were counted on the spot. The number alone, which one cell of the
    sheet holds, names the row; the counts stay values without a column."""
    typed = [
        {"zwrot": "ZW/2026/002", "przyjeto": "40", "uszkodzone": "40"},
        {"zwrot": "ZW/2026/003", "przyjeto": "10", "uszkodzone": "0"},
    ]
    found = trace_origins(typed, [RETURNS, RETURNS])
    assert found.origins == {"zwrot": Origin("Zwrot")}
    assert found.support == 2


def test_a_quantity_alone_names_no_row() -> None:
    """A quantity such as „40” could be in any row of any sheet: one such value, with the
    others not in the sheet, names nothing."""
    counts = Table(["Ilość", "Magazyn"], [{"Ilość": "40", "Magazyn": "M1"}], "stan.xlsx")
    found = trace_origins([{"przyjeto": "40", "uszkodzone": "3"}], [counts])
    assert found.origins == {}
    assert found.support == 0


def test_a_number_typed_with_its_leading_zeros() -> None:
    """An order the sheet holds as 302 (Excel drops the zeros) is searched for as 000000302:
    the column, typed to nine digits. An amount keeps its decimals, not a width."""
    assert readings("302", "000000302") == {("number", "000000000")}
    assert readings("000302", "000000302") == {("number", "000000000")}
    assert readings("302", "0302.00") == {("number", "0.00")}
    orders = Table(["Zamówienie"], [{"Zamówienie": "302"}, {"Zamówienie": "307"}], "zadanie.csv")
    found = trace_origins([{"search": "000000302"}], [orders])
    assert found.origins == {"search": Origin("Zamówienie", "number", "000000000")}


def test_a_date_the_sheet_writes_as_text_is_the_date_a_date_field_holds() -> None:
    """The sheet's „09/10/2012” typed into a date field (2012-09-10): read with the sheet's
    pattern, which a second recording settles (02/24/2017 is no 24th month)."""
    from maptelo.mapping.sources import written_dates

    assert written_dates("09/10/2012", "2012-09-10") == {("%m/%d/%Y", None)}
    assert written_dates("03/03/2027", "2027-03-03") == {("%d/%m/%Y", None), ("%m/%d/%Y", None)}
    assert written_dates("15.01.2027", "01/15/2027") == {("%d.%m.%Y", "%m/%d/%Y")}
    assert written_dates("2027-01-15", "2027-01-15") == set()  # an ISO cell: readings()
    table = Table(["Data"], [{"Data": "03/03/2027"}], "first")
    other = Table(["Data"], [{"Data": "02/24/2017"}], "second")
    found = trace_origins([{"data": "2027-03-03"}, {"data": "2017-02-24"}], [table, other])
    assert found.origins == {"data": Origin("Data", "date", None, "%m/%d/%Y")}
    alone = trace_origins([{"data": "2027-03-03"}], [table])
    assert "data" in alone.doubtful  # 03/03: which is the month, one recording cannot tell


def test_an_input_reads_the_sheet_date_as_the_sheet_writes_it() -> None:
    from datetime import date

    from maptelo.model.schema import InputSpec

    spec = InputSpec.model_validate({"type": "date", "written_as": "%m/%d/%Y"})
    assert spec.coerce("02/24/2017") == date(2017, 2, 24)
    assert spec.coerce("2017-02-24") == date(2017, 2, 24)


def test_a_time_the_sheet_writes_with_am_pm_is_the_time_a_time_field_holds() -> None:
    """The sheet's „9:22AM” typed into a time field (09:22): MiniWoB++ enter-time."""
    from datetime import time

    from maptelo.mapping.sources import written_times
    from maptelo.model.schema import InputSpec

    assert written_times("9:22AM", "09:22") == {("%I:%M%p", None)}
    assert written_times("9:22 PM", "21:22") == {("%I:%M %p", None)}
    assert written_times("09:22", "09:22") == set()  # the same text: a text value
    sheet = Table(["Godzina"], [{"Godzina": "3:37AM"}], "first")
    found = trace_origins([{"czas": "03:37"}], [sheet])
    assert found.origins == {"czas": Origin("Godzina", "time", None, "%I:%M%p")}
    spec = InputSpec.model_validate({"type": "time", "written_as": "%I:%M%p"})
    assert spec.coerce("1:02PM") == time(13, 2)
    assert spec.coerce("13:02") == time(13, 2)


def test_a_name_with_a_trade_mark_and_a_search_by_its_first_words() -> None:
    """The shop's „Gobi HeatTec® Tee” is the sheet's „Gobi HeatTec Tee”, and a person who
    typed only „Gobi” into the search box searched for it: both come from the column
    (WebArena-Verified 287; the robot types the whole name into the search)."""
    first = Table(["product"], [{"product": "Taurus Elements Shell"}], "first")
    second = Table(["product"], [{"product": "Gobi HeatTec Tee"}], "second")
    found = trace_origins(
        [
            {"search": "Taurus Elements Shell", "name": "Taurus Elements Shell"},
            {"search": "Gobi", "name": "Gobi HeatTec® Tee"},
        ],
        [first, second],
        searches={"search"},
    )
    assert found.origins == {"search": Origin("product"), "name": Origin("product")}
    plain = trace_origins(
        [
            {"search": "Taurus Elements Shell", "name": "Taurus Elements Shell"},
            {"search": "Gobi", "name": "Gobi HeatTec® Tee"},
        ],
        [first, second],
    )
    assert "search" not in plain.origins  # not a search box: a fragment is no value of it


def test_a_phone_number_typed_without_its_country_s_code() -> None:
    """The sheet writes „+1 2058812302”, the person searched the grid for 2058812302
    (WebArena-Verified 364). A number the sheet writes without a code is typed as it is, so a
    second recording agrees; alone, it is plain text."""
    assert readings("+1 2058812302", "2058812302") == {("text", "national")}
    assert readings("+48 600 100 200", "600 100 200") == {("text", "national")}
    assert readings("2137418080", "2137418080") == {("text", None), ("text", "national")}
    assert readings("+1 2058812302", "058812302") == set()
    assert readings("+12058812302", "2058812302") == set()  # where the code ends is unclear
    tasks = [
        Table(["PhoneNum"], [{"PhoneNum": "+1 2058812302"}], "zadanie.csv"),
        Table(["PhoneNum"], [{"PhoneNum": "2137418080"}], "zadanie.csv"),
    ]
    found = trace_origins([{"phone": "2058812302"}, {"phone": "2137418080"}], tasks)
    assert found.origins == {"phone": Origin("PhoneNum", "text", "national")}
    alone = trace_origins([{"phone": "2137418080"}], tasks[1:])
    assert alone.origins == {"phone": Origin("PhoneNum", "text", None)}


def test_a_search_typed_in_a_list_of_values_is_the_column_s_value() -> None:
    """Oracle Forms' list of values: K0010% for the customer K0010, 26386% for the item 26386-F
    (benchmark M1, M2). A value typed whole in one recording and searched for in another is the
    column's value: typed whole, it finds the same row."""
    assert readings("K0010", "K0010%") == {("text", "{}%")}
    assert readings("26386-F", "26386%") == {("text", "{}%")}
    assert readings("26386-F", "26%") == set()  # too little of it to say
    assert readings("26386-F", "2638%6") == set()  # a pattern, not a beginning
    rows = [{"Klient": "K0010", "Indeks": "26386-F"}, {"Klient": "K0015", "Indeks": "31830-D"}]
    sheet = Table(["Klient", "Indeks"], rows, "s")
    searched = trace_origins([{"klient": "K0010%"}], [sheet])
    assert searched.origins == {"klient": Origin("Klient", "text", "{}%")}
    typed = [{"indeks": "26386-F", "klient": "K0010"}, {"indeks": "31830%", "klient": "K0015"}]
    both = trace_origins(typed, [sheet, sheet])
    assert both.origins["indeks"] == Origin("Indeks", "text", None)


def test_a_date_in_oracle_s_polish_mask() -> None:
    """WCR (benchmark M2) shows dates as an Oracle set to Polish does: 01-LIS-2026."""
    assert readings("2026-11-01", "01-LIS-2026") == {("date", "DD-MON-RRRR")}
    assert readings("2026-10-31", "31-PAŹ-2026") == {("date", "DD-MON-RRRR")}
    assert readings("2026-11-01", "01-NOV-2026") == {("date", "DD-MON-YYYY")}
    assert readings("2026-03-01", "01-MAR-2026") == {
        ("date", "DD-MON-YYYY"),
        ("date", "DD-MON-RRRR"),
    }


def test_words_written_around_a_value_of_the_sheet() -> None:
    """A correction's description names the delivery note: the same words around the sheet's
    WZ number in every recording (benchmark M6). A short number or a word is in any text."""
    sentence = "Kwota netto niezgodna z dokumentem WZ/2026/01018."
    assert readings("WZ/2026/01018", sentence) == {
        ("text", "Kwota netto niezgodna z dokumentem {}.")
    }
    assert readings("10", "Termin 10 dni") == set()
    assert readings("Nowa", "Nowa cena") == set()
    rows = [{"WZ": "WZ/2026/01018"}, {"WZ": "WZ/2026/02017"}]
    sheet = Table(["WZ"], rows, "s")
    typed = [{"opis": sentence}, {"opis": "Kwota netto niezgodna z dokumentem WZ/2026/02017."}]
    both = trace_origins(typed, [Table(["WZ"], [rows[0]], "a"), Table(["WZ"], [rows[1]], "b")])
    assert both.origins["opis"] == Origin("WZ", "text", "Kwota netto niezgodna z dokumentem {}.")
    assert sheet.rows  # the sheet as people keep it


def test_a_path_holding_the_customer_is_the_file_s_not_the_customer_s() -> None:
    """A negotiator's file typed as its path (benchmark M3): the path holds the file's name and,
    inside it, the customer's number. The file's name covers more of it: that is the value."""
    from maptelo.data.tables import Table

    table = Table(
        headers=["Plik", "Klient"],
        rows=[
            {"Plik": "cennik_K0010_2026-11.csv", "Klient": "K0010"},
            {"Plik": "cennik_K0018_2026-11.csv", "Klient": "K0018"},
        ],
        source="pliki.csv",
    )
    path = r"C:\Temp\maptelo-bench\m3\seed1\cennik_K0010_2026-11.csv"
    found = trace_origins([{"plik": path, "klient": "K0010%"}], [table])
    assert found.origins["plik"] == Origin(
        "Plik", "text", path.replace("cennik_K0010_2026-11.csv", "{}")
    )
    assert "plik" not in found.doubtful


def test_the_row_whose_cells_cover_the_most_of_the_path_is_the_records() -> None:
    """Two files of one customer in the sheet (benchmark M3): the path typed holds the
    customer's K0010, which both rows have, and the file's name, which one has. Both rows hold
    as many of the values; the one whose file's name is in the path is the record's."""
    from maptelo.data.tables import Table

    table = Table(
        headers=["Plik", "Klient", "Zatwierdzający"],
        rows=[
            {"Plik": "cennik_K0010_2026-11.csv", "Klient": "K0010", "Zatwierdzający": "Ewa Nowak"},
            {"Plik": "cennik_K0018_2026-11.csv", "Klient": "K0018", "Zatwierdzający": "Jan Lis"},
            {"Plik": "aneks_K0010_2026-12.csv", "Klient": "K0010", "Zatwierdzający": "Ewa Nowak"},
        ],
        source="pliki.csv",
    )
    path = r"C:\Temp\maptelo-bench\m3\seed1\aneks_K0010_2026-12.csv"
    typed = {"plik": path, "cennik": "K0010%", "zatwierdzajacy": "Ewa Nowak"}
    found = trace_origins([typed], [table])
    assert found.rows == [table.rows[2]]
    assert found.origins["plik"] == Origin(
        "Plik", "text", path.replace("aneks_K0010_2026-12.csv", "{}")
    )
    assert found.origins["zatwierdzajacy"] == Origin("Zatwierdzający", "text", None)


def test_a_file_told_by_its_name_is_the_cell_naming_it_by_its_path() -> None:
    """A browser tells an upload by the file's name alone (benchmark M7): the sheet's Plik
    names it by its path. The chain's K0009, which the name holds, is not its column (the
    robot looked for a file „K0017”)."""
    from maptelo.data.tables import Table

    table = Table(
        headers=["Sieć", "Plik"],
        rows=[
            {"Sieć": "K0009", "Plik": r"C:\Temp\m7\seed1\cennik_K0009.xlsx"},
            {"Sieć": "K0017", "Plik": r"C:\Temp\m7\seed1\cennik_K0017.xlsx"},
        ],
        source="cenniki.xlsx",
    )
    found = trace_origins([{"plik": "cennik_K0009.xlsx", "siec": "K0009"}], [table])
    assert found.origins["plik"] == Origin("Plik", "text", None)
    assert found.origins["siec"] == Origin("Sieć", "text", None)
