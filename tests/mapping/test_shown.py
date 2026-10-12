"""Where a typed value had been shown: places a robot can read again, and values too plain
to be taken for a copy."""

from __future__ import annotations

from maptelo.mapping.shown import Place, best, distinctive, names_one, places

RESULT = """- main:
  - heading "Wynik wyszukiwania" [level=2]
  - term: Nazwa
  - definition: Zbiciak i syn s.c.
  - term: NIP
  - definition: "3123435783"
  - term: Numer rachunku
  - definition: PL73437049919574900522116933
"""

RATES = """- table "Tabela 182/A/NBP/2026 z dnia 2026-10-06":
  - rowgroup:
    - row "Waluta Kod Kurs średni":
      - columnheader "Waluta"
      - columnheader "Kod"
      - columnheader "Kurs średni"
  - rowgroup:
    - row "euro EUR 4,3806":
      - cell "euro"
      - cell "EUR"
      - cell "4,3806"
    - row "dolar amerykański USD 3,8550":
      - cell "dolar amerykański"
      - cell "USD"
      - cell "3,8550"
"""


def test_a_value_under_a_term_is_found_by_the_term() -> None:
    assert best(places(RESULT, "Zbiciak i syn s.c.")) == Place("term", "Nazwa")
    assert best(places(RESULT, " PL73437049919574900522116933 ")) == Place("term", "Numer rachunku")


def test_a_value_in_a_table_is_found_by_its_column_and_keeps_its_row() -> None:
    place = best(places(RATES, "4,3806"))
    assert place is not None
    assert (place.kind, place.label, place.table) == (
        "cell",
        "Kurs średni",
        "Tabela 182/A/NBP/2026 z dnia 2026-10-06",
    )
    assert dict(place.row)["Kod"] == "EUR"
    assert len(place.rows) == 2


def test_a_field_that_shows_a_value_is_a_place_too() -> None:
    aria = '- textbox "Numer przesyłki":\n  - /placeholder: SP...\n  - text: SP261007783244\n'
    assert best(places(aria, "SP261007783244")) == Place("field", "Numer przesyłki", "textbox")


def test_a_value_inside_running_text_is_read_after_its_words() -> None:
    """An e-mail's „Termin dostawy: 2026-10-20” (benchmark p11): the words before it, back to
    a number or the end of the part before."""
    aria = "- paragraph: Prosimy o 12 sztuk tacy 48212-B na adres Leśna 5.\n"
    assert places(aria, "48212-B") == [Place("words", "sztuk tacy", lead="sztuk tacy")]
    aria = "- paragraph: Ilość: 25 szt. Termin dostawy: 2026-10-20\n"
    assert places(aria, "2026-10-20") == [Place("words", "Termin dostawy", lead="Termin dostawy:")]
    assert places(aria, "Leśna 5") == []  # a value of several words: no single word to read


def test_one_value_under_two_terms_leaves_it_unknown_which_was_read() -> None:
    aria = (
        "- term: NIP\n- definition: 3123435783\n- term: Numer klienta\n- definition: 3123435783\n"
    )
    assert len(places(aria, "3123435783")) == 2
    assert best(places(aria, "3123435783")) is None


def test_short_and_common_values_are_not_taken_for_copies() -> None:
    for plain in ("4", "12", "Tak", "Czynny", "EUR"):
        assert not distinctive(plain), plain
    for copied in ("4,3806", "Zbiciak i syn s.c.", "PL73437049919574900522116933", "SP2610"):
        assert distinctive(copied), copied


def test_what_can_name_a_record_in_an_address() -> None:
    for record in ("C001", "ZS/2026/0002", "3123435783", "48212-B"):
        assert names_one(record), record
    for chance in ("2", "48", "EUR", "Tak"):
        assert not names_one(chance), chance


def test_an_amount_or_a_date_is_what_a_row_says_not_what_names_it() -> None:
    from maptelo.mapping.shown import measure

    for value in ("129,90", "11.06", "1 234,50 zł", "1.234,50", "2027-01-15", "15.01.2027"):
        assert measure(value), value
    for value in ("K0028", "ZS/2026/0002", "Jan Kowalski", "48212-B", "12345"):
        assert not measure(value), value


def test_a_message_copied_whole_is_read_after_its_label() -> None:
    checks = """- main:
  - status: "Kontrole: Kwota poza tolerancją: zamówienie x przyjęcie = 5760.00 zł"
  - heading "Kontrole" [level=2]
  - list:
    - listitem: ✔ Netto + VAT = brutto
    - listitem: "✘ Kwota poza tolerancją: zamówienie x przyjęcie = 5760.00 zł"
  - textbox "Powód wstrzymania"
"""
    found = places(checks, "Kwota poza tolerancją: zamówienie x przyjęcie = 5760.00 zł")
    assert found == [Place("words", "Kontrole", lead="Kontrole", rest=True)]
