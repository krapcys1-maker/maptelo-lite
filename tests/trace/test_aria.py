"""Reading accessibility snapshots: a name with „: ” in it makes YAML quote the whole line's key
(benchmark g031, g040: the button „Wybierz: Kontrahent” was not seen on the screen, so the step
before it waited for it to appear)."""

from __future__ import annotations

from maptelo.trace.aria import parse_aria

SNAPSHOT = """- main:
  - textbox "Data od"
  - 'button "Wybierz: Kontrahent"': …
  - 'link "Klient''s: K0028"'
  - listitem: "✘ Kwota poza tolerancją: zamówienie x przyjęcie = 5760.00 zł"
  - button "Zapisz"
"""


def test_a_name_with_a_colon_is_read_from_its_quoted_line() -> None:
    root = parse_aria(SNAPSHOT)
    button = root.find("button", "Wybierz: Kontrahent")
    assert button is not None
    assert button.value == "…"
    assert root.find("link", "Klient's: K0028") is not None
    item = root.find("listitem")
    assert item is not None
    assert item.value == "✘ Kwota poza tolerancją: zamówienie x przyjęcie = 5760.00 zł"
    assert [n.role for n in root.find_all("button")] == ["button", "button"]
