"""M2 acceptance: each committed recording maps to the model its ground truth describes."""

from __future__ import annotations

from pathlib import Path

import pytest

from maptelo.mapping import map_trace
from maptelo.model import Severity, dump_model, lint, parse_model
from maptelo.trace import load_trace
from minierp.scenarios import PROCESS, SCENARIOS, Scenario

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recordings" / PROCESS


def mapped(scenario: Scenario, lang: str = "pl"):  # type: ignore[no-untyped-def]
    return map_trace(load_trace(FIXTURES / scenario.id), lang=lang)  # type: ignore[arg-type]


def element_of(step) -> str:  # type: ignore[no-untyped-def]
    if step.action.value == "navigate":
        return str(step.value)
    first = step.target[0]
    return first.name or first.label or first.describe()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_map_matches_ground_truth(scenario: Scenario) -> None:
    expected = scenario.expected_map()
    result = mapped(scenario)
    model = result.model
    assert [f"{s.action.value} {element_of(s)}" for s in model.steps] == expected["steps"]
    assert list(model.inputs) == expected["inputs"]
    assert len(model.exceptions) == expected["exceptions"]
    assert len(model.interrupts) == expected["interrupts"]
    assert len(model.preconditions) == expected["preconditions"]
    rows = [s for s in model.steps if s.within is not None]
    if expected["row_rule"]:
        assert rows[0].within is not None
        assert rows[0].within.where == expected["row_rule"]
    else:
        assert rows == []


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_map_is_valid_and_round_trips(scenario: Scenario) -> None:
    model = mapped(scenario).model
    errors = [
        i for i in lint(model) if i.severity is Severity.WARNING and "effect" not in i.message
    ]
    assert errors == [], "only the missing effect may be reported from a single recording"
    assert parse_model(dump_model(model)) == model


def test_rejections_become_exceptions_with_placeholders() -> None:
    by_id = {s.id: s for s in SCENARIOS}
    wrong_cpn = mapped(by_id["10-wrong-cpn-then-right"]).model
    assert wrong_cpn.exceptions["no_product_found_for_cpn"].description == (
        "No product found for CPN {cpn}."
    )
    search = wrong_cpn.step("click_search")
    assert search.on_outcome is not None
    assert search.on_outcome["no_product_found_for_cpn"].raise_ == "no_product_found_for_cpn"
    past_date = mapped(by_id["09-past-date-corrected"]).model
    assert list(past_date.exceptions) == ["valid_from_cannot_be_in_the_past"]


def test_inputs_are_typed_from_their_values() -> None:
    model = mapped(SCENARIOS[1]).model
    assert {name: spec.type.value for name, spec in model.inputs.items()} == {
        "customer": "string",
        "cpn": "string",
        "price": "decimal",
        "valid_from": "date",
    }


def test_screens_become_states_with_fingerprints() -> None:
    model = mapped(SCENARIOS[9]).model  # visits the search results page too
    assert set(model.states) == {"customer_prices", "pricing_product"}
    assert model.states["customer_prices"].url == "/pricing*"
    product = model.states["pricing_product"]
    assert product.url == "/pricing/product/*"
    assert product.visible is not None
    assert product.visible[0].name == "Price versions"


def test_english_intents() -> None:
    model = mapped(SCENARIOS[1], lang="en").model
    assert [s.intent for s in model.steps][:4] == [
        "Open the “Customer prices” screen",
        "Choose a value from the “Customer” list",
        "Fill in the “CPN” field",
        "Click “Search”",
    ]


def test_polish_intents_quote_the_screen_s_words() -> None:
    """A field's name is the screen's own word, in quotes, never part of the sentence
    („Wpisz Price”, „Wybierz Customer z listy”: what a work instruction must not say)."""
    model = mapped(SCENARIOS[1]).model
    assert [s.intent for s in model.steps][1:3] == [
        "Wybierz wartość z listy „Customer”",
        "Wypełnij pole „CPN”",
    ]


def test_a_map_s_documents_name_its_recording_by_its_day(tmp_path: Path) -> None:
    """The documents of one recording's map are for the people who do the process: the day it
    was recorded as their language writes it, the product that made them, and none of the
    model file's English findings (those are for whoever edits the model)."""
    from maptelo.export import write_map_bundle

    files = write_map_bundle(mapped(SCENARIOS[0]), tmp_path / "pl", lang="pl")
    sop = files["sop"].read_text(encoding="utf-8")
    assert "· nagranie: 08.10.2026 (01-login-single-version)*" in sop
    assert "na podstawie nagrania z 08.10.2026." in sop
    assert "*Wygenerowano w programie Maptelo" in sop
    report = files["report"].read_text(encoding="utf-8")
    assert "Ostrzeżenia" not in report
    assert "no effects declared" not in report
    english = write_map_bundle(mapped(SCENARIOS[0], "en"), tmp_path / "en", lang="en")
    assert "· recording: 8 October 2026 (" in english["sop"].read_text(encoding="utf-8")


def test_notes_name_what_needs_confirming() -> None:
    notes = mapped(SCENARIOS[1]).notes
    assert any("Status = Active" in n for n in notes)
    popup_notes = mapped(SCENARIOS[7]).notes
    assert any("Session expiring" in n for n in popup_notes)


def test_a_step_in_a_window_runs_only_while_that_window_is_open() -> None:
    """The confirmation comes only for a large change: its "Confirm" is pressed only when the
    window is there (benchmark: a branch step done always)."""
    from maptelo.model.schema import Locator

    model = map_trace(load_trace(FIXTURES / "05-large-change-confirmed")).model
    confirm = next(s for s in model.steps if s.target and s.target[0].name == "Confirm")
    assert confirm.when is not None
    assert confirm.when.visible == Locator(role="dialog", name="Confirm price change")
