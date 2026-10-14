"""A decision made where the screen offered another (benchmark M6: „Akceptuj” clicked in an
invoice's row that also has the link „Korekta (CN)”). The recording shows which was chosen,
never when the other is: the map leaves the decision to a person and says why, and the brief
asks the rule. The model of one such recording, and a language model given its brief, accepted
every invoice: nothing said the row offered more."""

from __future__ import annotations

from maptelo.export.ai_brief import render_ai_brief
from maptelo.mapping import map_trace
from maptelo.mapping.choices import decision_kind, offered_choices
from maptelo.trace import ElementInfo, Trace
from maptelo.trace.aria import parse_aria
from maptelo.trace.schema import RowContext
from tests.mapping.test_many_apps import ERP, Recording, found_by_its_words

INVOICES = f"{ERP}/faktury"
ROW = {"Numer": "SBI/K0009/2026/0019", "WZ": "WZ/2026/01019", "Netto": "13 749,68 zł"}
SCREEN = """- navigation "Menu":
  - link "Reklamacje"
- main:
  - heading "Faktury samofakturowania" [level=1]
  - button "Odrzuć zaznaczone"
  - table "Faktury":
    - rowgroup:
      - row "Numer WZ Netto":
        - columnheader "Numer"
        - columnheader "WZ"
        - columnheader "Netto"
        - columnheader
    - rowgroup:
      - row "SBI/K0009/2026/0019 WZ/2026/01019 13 749,68 zł Akceptuj Korekta (CN)":
        - cell "SBI/K0009/2026/0019"
        - cell "WZ/2026/01019"
        - cell "13 749,68 zł"
        - cell "Akceptuj Korekta (CN)":
          - button "Akceptuj"
          - link "Korekta (CN)":
            - /url: /dokumenty/19/korekta
      - row "SBI/K0017/2026/0004 WZ/2026/01018 24 506,61 zł Akceptuj":
        - cell "SBI/K0017/2026/0004"
        - cell "WZ/2026/01018"
        - cell "24 506,61 zł"
        - cell "Akceptuj":
          - button "Akceptuj"
"""
ASKED = (
    SCREEN
    + """- dialog "Potwierdzenie":
  - button "Potwierdź"
  - button "Anuluj"
"""
)


def accept_button(cells: dict[str, str] | None = None) -> ElementInfo:
    row = RowContext(table="Faktury", cells={**(cells or ROW), "#4": "AkceptujKorekta (CN)"})
    info = ElementInfo(tag="button", role="button", name="Akceptuj", text="Akceptuj", row=row)
    return found_by_its_words(info)


def accepted(name: str = "01", screen: str = SCREEN) -> Trace:
    r = Recording()
    shown = r.state(INVOICES, screen)
    asked = r.state(INVOICES, screen + ASKED.removeprefix(SCREEN))
    r.add("navigate", INVOICES, value=INVOICES, state_after=shown)
    r.add("click", INVOICES, target=accept_button(), state_before=shown, state_after=asked)
    confirm = ElementInfo(tag="button", role="button", name="Potwierdź", dialog="Potwierdzenie")
    r.add("click", INVOICES, target=found_by_its_words(confirm), state_before=asked,
          state_after=shown, sent=["POST /faktury/19/akceptacja"])  # fmt: skip
    return r.trace(name=name)


def test_what_a_command_decides() -> None:
    assert decision_kind("Akceptuj") == "grant"
    assert decision_kind("Zatwierdź wniosek") == "grant"
    assert decision_kind("Odrzuć reklamację") == "refuse"
    assert decision_kind("Korekta (CN)") == "dispute"
    assert decision_kind("Wstrzymaj płatność") == "dispute"
    assert decision_kind("Podgląd") is None
    assert decision_kind("Do akceptacji") is None  # a menu's page, not a decision
    assert decision_kind("Reklamacje") is None


def test_the_rows_other_decision_is_the_one_offered() -> None:
    """Only the row's own commands count: the menu's „Reklamacje” and the list's „Odrzuć
    zaznaczone” are not this invoice's other decision."""
    screen = parse_aria(SCREEN)
    assert offered_choices(screen, accept_button(), "Akceptuj") == ["Korekta (CN)"]
    second = {"Numer": "SBI/K0017/2026/0004", "WZ": "WZ/2026/01018", "Netto": "24 506,61 zł"}
    assert offered_choices(screen, accept_button(second), "Akceptuj") == []
    assert offered_choices(screen, accept_button(), "Podgląd") == []
    plain = ElementInfo(tag="button", role="button", name="Akceptuj")
    assert offered_choices(screen, plain, "Akceptuj") == ["Odrzuć zaznaczone"]


def test_the_map_leaves_the_decision_to_a_person_and_says_why() -> None:
    mapped = map_trace(accepted())
    step = next(s for s in mapped.model.steps if s.alternatives)
    assert step.alternatives == ["Korekta (CN)"]
    assert step.executor.value == "human"
    assert any("„Korekta (CN)”" in note and "decyzja" in note for note in mapped.notes)


def test_the_brief_says_the_decision_and_asks_its_rule() -> None:
    mapped = map_trace(accepted())
    brief = render_ai_brief(mapped.model, lang="pl", notes=mapped.notes, one_recording=True)
    assert "**Decyzja:** nagrania pokazują tylko „Akceptuj”" in brief
    assert "w wierszu tabeli jest też „Korekta (CN)”" in brief
    assert "kiedy wybierasz „Akceptuj”, a kiedy „Korekta (CN)”?" in brief
    english = render_ai_brief(map_trace(accepted()).model, lang="en", one_recording=True)
    assert "when do you choose “Akceptuj”, and when “Korekta (CN)”?" in english
