from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from maptelo.model.schema import ProcessModel
from tests.model.helpers import minimal_model, with_steps

CLICK_SAVE: dict[str, Any] = {
    "id": "save",
    "intent": "Save",
    "action": "click",
    "target": {"role": "button", "name": "Save"},
    "risk": "commit",
}


def _rejects(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ProcessModel.model_validate(data)


def test_unknown_input_reference() -> None:
    step = {"id": "s", "intent": "x", "action": "fill", "target": {"label": "A"}}
    _rejects(with_steps({**step, "value": "$inputs.price"}), "unknown input 'price'")


def test_placeholders_inside_text_are_checked() -> None:
    step = {"id": "go", "intent": "x", "action": "navigate", "value": "/p/{inputs.sku}"}
    _rejects(with_steps(step), "unknown input 'sku'")


def test_dollar_reference_inside_text_is_rejected() -> None:
    step = {"id": "go", "intent": "x", "action": "navigate", "value": "/p/$inputs.cpn"}
    _rejects(with_steps(step), "use \\{inputs.name\\} placeholders")


def test_variables_must_be_read_before_use() -> None:
    use = {
        "id": "use",
        "intent": "x",
        "action": "fill",
        "target": {"label": "B"},
        "value": "$vars.old",
    }
    read = {
        "id": "read",
        "intent": "x",
        "action": "read",
        "target": {"label": "A"},
        "save_as": "old",
    }
    _rejects(with_steps(use, read), "variable 'old' is used before")
    ProcessModel.model_validate(with_steps(read, use))


def test_verifiers_may_not_use_screen_variables() -> None:
    read = {
        "id": "read",
        "intent": "x",
        "action": "read",
        "target": {"label": "A"},
        "save_as": "old",
    }
    effect = {
        "id": "done",
        "description": "x",
        "verifier": {"url": "/api/x", "expect": {"price": "$vars.old"}},
    }
    _rejects(with_steps(read, effects=[effect]), "verification must not depend on")


def test_unknown_states_exceptions_steps_and_effects() -> None:
    step = {
        "id": "search",
        "intent": "x",
        "action": "click",
        "target": {"label": "Go"},
        "in_state": "nowhere",
        "outcomes": {"found": {"state": "product"}, "missing": {"url": "/404"}},
        "on_outcome": {"missing": {"raise": "not_found"}, "found": {"goto": "later"}},
        "verify_effects": ["ghost"],
    }
    with pytest.raises(ValidationError) as caught:
        ProcessModel.model_validate(with_steps(step, idempotency={"skip_if_effects": ["gone"]}))
    message = str(caught.value)
    for expected in (
        "unknown state 'nowhere'",
        "unknown state 'product'",
        "raises unknown exception 'not_found'",
        "jumps to unknown step 'later'",
        "unknown effect 'ghost'",
        "idempotency: unknown effect 'gone'",
    ):
        assert expected in message


def test_goto_own_step_is_rejected() -> None:
    step = {
        "id": "loop",
        "intent": "x",
        "action": "wait",
        "outcomes": {"a": {"url": "/a"}, "b": {"url": "/b"}},
        "on_outcome": {"a": {"goto": "loop"}},
    }
    _rejects(with_steps(step), "jumps to its own step")


def test_duplicate_step_ids() -> None:
    _rejects(with_steps(CLICK_SAVE, CLICK_SAVE), "id 'save' is used more than once")


def test_interrupt_states_must_exist() -> None:
    interrupt = {
        "id": "popup",
        "when": {"state": "dialog"},
        "do": [{"action": "click", "target": {"role": "button", "name": "OK"}}],
    }
    _rejects(minimal_model(interrupts=[interrupt]), "unknown state 'dialog'")


def test_interrupt_handlers_are_limited() -> None:
    interrupt = {"id": "popup", "when": {"url": "/x"}, "do": [{"action": "navigate", "value": "/"}]}
    _rejects(minimal_model(interrupts=[interrupt]), "interrupt handlers may only use")
