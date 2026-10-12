from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from maptelo.model.schema import (
    InputSpec,
    Locator,
    Predicate,
    ProcessModel,
    RiskClass,
    Step,
)
from tests.model.helpers import minimal_model


def test_minimal_model_is_valid() -> None:
    model = ProcessModel.model_validate(minimal_model())
    assert [s.id for s in model.steps] == ["open", "type_cpn"]


def test_unquoted_schema_version_is_accepted() -> None:
    assert ProcessModel.model_validate(minimal_model(schema_version=0.1)).schema_version == "0.1"


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProcessModel.model_validate(minimal_model(owner="someone"))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({}, "got: none"),
        ({"role": "button", "label": "Save"}, "got: role, label"),
        ({"label": "Price", "name": "x"}, "only valid together with 'role'"),
    ],
)
def test_locator_needs_exactly_one_strategy(data: dict[str, str], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Locator.model_validate(data)


def test_locator_description() -> None:
    assert Locator(role="button", name="Save").describe() == 'role=button name="Save"'
    assert Locator(testid="cpn-input").describe() == 'testid="cpn-input"'


def test_single_locator_becomes_a_one_rung_ladder() -> None:
    step = Step.model_validate(
        {"id": "s", "intent": "x", "action": "click", "target": {"text": "Go"}}
    )
    assert step.target is not None
    assert [loc.text for loc in step.target] == ["Go"]


def _step(**fields: Any) -> dict[str, Any]:
    return {"id": "s", "intent": "Do it", **fields}


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"action": "click"}, "requires 'target'"),
        ({"action": "fill", "target": {"label": "A"}}, "requires 'value'"),
        ({"action": "navigate", "value": "/x", "target": {"label": "A"}}, "does not take 'target'"),
        ({"action": "click", "target": {"label": "A"}, "value": "x"}, "does not take 'value'"),
        ({"action": "read", "target": {"label": "A"}}, "'save_as' is required"),
        ({"action": "wait"}, "needs 'expect' or 'outcomes'"),
        (
            {
                "action": "wait",
                "expect": {"url": "/a"},
                "outcomes": {"a": {"url": "/a"}, "b": {"url": "/b"}},
            },
            "either 'expect' or 'outcomes'",
        ),
        (
            {
                "action": "wait",
                "outcomes": {"ok": {"url": "/a"}, "bad": {"url": "/b"}},
                "on_outcome": {"missing": {"continue": True}},
            },
            "undeclared outcomes: missing",
        ),
        (
            {"action": "click", "target": {"label": "A"}, "executor": "agent", "fallback": "agent"},
            "must differ",
        ),
    ],
)
def test_step_rules(fields: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Step.model_validate(_step(**fields))


def test_effective_risk_defaults_by_action() -> None:
    nav = Step.model_validate(_step(action="navigate", value="/x"))
    fill = Step.model_validate(_step(action="fill", target={"label": "A"}, value="1"))
    save = Step.model_validate(_step(action="click", target={"label": "Save"}, risk="commit"))
    assert nav.effective_risk is RiskClass.READ
    assert fill.effective_risk is RiskClass.DRAFT
    assert save.effective_risk is RiskClass.COMMIT


def test_predicate_needs_exactly_one_kind() -> None:
    with pytest.raises(ValidationError, match="got: url, state"):
        Predicate.model_validate({"url": "/a", "state": "home"})


def test_predicate_combinators_use_yaml_keywords() -> None:
    predicate = Predicate.model_validate({"all": [{"url": "/a"}, {"not": {"state": "home"}}]})
    assert len(predicate.walk()) == 4  # all, url, not, state
    dumped = predicate.model_dump(by_alias=True, exclude_none=True)
    assert set(dumped) == {"all"}


@pytest.mark.parametrize(
    ("spec", "raw", "expected"),
    [
        ({"type": "decimal"}, "129,90", Decimal("129.90")),
        ({"type": "decimal"}, 135.0, Decimal("135.0")),
        ({"type": "integer"}, "42", 42),
        ({"type": "date"}, "2026-12-01", date(2026, 12, 1)),
        ({"type": "date"}, date(2026, 12, 1), date(2026, 12, 1)),
        ({"type": "boolean"}, "tak", True),
        ({"type": "string", "pattern": "^C[0-9]{3}$"}, "C001", "C001"),
        ({"type": "string"}, 48212, "48212"),
    ],
)
def test_input_coercion(spec: dict[str, Any], raw: object, expected: object) -> None:
    assert InputSpec.model_validate(spec).coerce(raw) == expected


@pytest.mark.parametrize(
    ("spec", "raw", "message"),
    [
        ({"type": "decimal"}, "twelve", "expected a number"),
        ({"type": "decimal", "min": "0.01"}, "0", "below the minimum"),
        ({"type": "integer", "max": 10}, 11, "above the maximum"),
        ({"type": "date"}, "01.12.2026", "YYYY-MM-DD"),
        ({"type": "date"}, "2026-02-30", "YYYY-MM-DD"),
        ({"type": "string", "pattern": "^C[0-9]{3}$"}, "X1", "does not match"),
        ({"type": "string", "choices": ["EUR", "PLN"]}, "USD", "not one of"),
        ({"type": "boolean"}, "maybe", "true/false"),
    ],
)
def test_input_coercion_rejects(spec: dict[str, Any], raw: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        InputSpec.model_validate(spec).coerce(raw)


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ({"type": "integer", "pattern": "x"}, "only valid for string"),
        ({"type": "string", "min": 1}, "only valid for integer and decimal"),
        ({"type": "decimal", "min": 5, "max": 1}, "greater than 'max'"),
        ({"type": "string", "pattern": "("}, "not a valid regex"),
        ({"type": "string", "pattern": "^C[0-9]{3}$", "example": "X1"}, "does not match"),
    ],
)
def test_input_spec_rules(spec: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        InputSpec.model_validate(spec)
