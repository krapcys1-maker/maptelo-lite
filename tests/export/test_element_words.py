"""What an element is, in the SOP's words (the clean-Windows Lite test of 12.10: a Polish SOP said
„pojawia się field „price””: an element found by the name its form sends was named by that
way of finding it)."""

from __future__ import annotations

import pytest

from maptelo.export.describe import element_absent, element_appears, predicate_text
from maptelo.model.schema import Locator, Predicate, ProcessModel


@pytest.mark.parametrize(
    ("locator", "appears", "absent"),
    [
        (Locator(field="price"), "pojawia się pole „price”", "nie widać pola „price”"),
        (
            Locator(role="cell", name="Status"),
            "pojawia się komórka „Status”",
            "nie widać komórki „Status”",
        ),
        (Locator(role="option", name="DHL"), "pojawia się opcja „DHL”", "nie widać opcji „DHL”"),
        (Locator(css="#x"), "pojawia się element „#x”", "nie widać elementu „#x”"),
    ],
)
def test_polish_words_for_an_element(locator: Locator, appears: str, absent: str) -> None:
    assert element_appears(locator, "pl") == appears
    assert element_absent(locator, "pl") == absent


def test_english_keeps_its_role_names() -> None:
    assert element_appears(Locator(field="price"), "en") == "the “price” field appears"
    assert element_appears(Locator(role="cell", name="Status"), "en") == "the “Status” cell appears"


def test_one_element_found_two_ways_is_said_once() -> None:
    """The same field by its label and by the name its form sends: „pojawia się pole „Price” /
    pojawia się pole „price”” said one thing twice."""
    model = ProcessModel.model_validate(
        {
            "schema_version": "0.1",
            "id": "p",
            "title": "P",
            "version": 1,
            "application": {"name": "MiniERP", "base_url": "http://minierp.test:8000"},
            "steps": [{"id": "s1", "intent": "Otwórz", "action": "navigate", "value": "/"}],
        }
    )
    either = Predicate.model_validate(
        {
            "any": [
                {"visible": {"role": "textbox", "name": "Price"}},
                {"visible": {"field": "price"}},
            ]
        }
    )
    assert predicate_text(either, model, "pl") == "pojawia się pole „Price”"
    other = Predicate.model_validate(
        {"any": [{"visible": {"role": "textbox", "name": "Price"}}, {"visible": {"field": "cena"}}]}
    )
    assert (
        predicate_text(other, model, "pl") == "pojawia się pole „Price” / pojawia się pole „cena”"
    )
