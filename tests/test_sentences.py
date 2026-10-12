"""Values read from sentences (maptelo.sentences): the words a value follows, and the value
after them again."""

from __future__ import annotations

from maptelo.sentences import lead_before, words_after

MAIL = (
    "Produkt: 16218-E (Przekładka tekturowa 380x280 3 mm) Ilość: 25 szt. Termin dostawy: 2026-10-20"
)


def test_the_words_a_value_follows_are_its_label_or_its_message() -> None:
    assert lead_before(MAIL, "2026-10-20") == "Termin dostawy:"
    assert lead_before(MAIL, "25") == "Ilość:"  # not the product's words before it
    assert lead_before(MAIL, "16218-E") == "Produkt:"
    assert lead_before("Zgłoszono szkodę SZK/2026/0001.", "SZK/2026/0001") == "Zgłoszono szkodę"
    text = "proszę o realizację zamówienia nr PO-10001:"
    assert lead_before(text, "PO-10001") == "realizację zamówienia nr"  # three words at most


def test_no_words_when_the_value_stands_alone_or_twice() -> None:
    assert lead_before("SZK/2026/0001", "SZK/2026/0001") is None
    assert lead_before("Koniec. SZK/2026/0001", "SZK/2026/0001") is None
    assert lead_before("Nr A1, potem nr A1", "A1") is None  # which one is meant?
    assert lead_before("Kwota 1250 zł", "125") is None  # not a word of the text


def test_the_value_after_the_words_is_read_again() -> None:
    assert words_after(["Zgłoszono szkodę SZK/2026/0007."], "Zgłoszono szkodę") == {"SZK/2026/0007"}
    assert words_after(["Termin\ndostawy: 2026-11-05 i dalej"], "Termin dostawy:") == {"2026-11-05"}
    texts = ["Odebrane", MAIL.replace("25", "7")]  # a page and its frame
    assert words_after(texts, "Ilość:") == {"7"}
    assert words_after(["Ilość: 2 i Ilość: 3"], "Ilość:") == {"2", "3"}  # for a person
    assert words_after(["Nic tu nie ma."], "Termin dostawy:") == set()


def test_a_whole_message_after_its_label() -> None:
    """The failed check copied as the reason for holding an invoice (benchmark p24)."""
    from maptelo.sentences import lead_of_rest, rest_after

    message = "Kontrole: Kwota poza tolerancją: zamówienie x przyjęcie = 8 520,00 zł"
    rest = "Kwota poza tolerancją: zamówienie x przyjęcie = 8 520,00 zł"
    assert lead_of_rest(message, rest) == "Kontrole"
    assert lead_of_rest("✘ " + rest, rest) is None  # a mark is no label
    assert lead_of_rest("Faktura 12/2026: " + rest, rest) is None  # a number differs every time
    assert lead_of_rest(rest, rest) is None
    page = f"Dokument DOK/1\nKontrole\n{message}\n✔ Netto + VAT = brutto\n✘ {rest}"
    assert rest_after([page], "Kontrole") == {rest}
    assert rest_after(["Kontrole: wszystkie zgodne."], "Kontrole") == {"wszystkie zgodne."}
