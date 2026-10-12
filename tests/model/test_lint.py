from __future__ import annotations

from maptelo.model import Severity, lint
from maptelo.model.schema import ProcessModel
from tests.model.helpers import minimal_model, with_steps

EFFECT = {
    "id": "saved",
    "description": "Record exists",
    "verifier": {"url": "/api/records/{inputs.cpn}", "expect": {"exists": True}},
}


def _messages(model: ProcessModel) -> list[str]:
    return [str(issue) for issue in lint(model)]


def test_model_without_effects_cannot_be_verified() -> None:
    issues = lint(ProcessModel.model_validate(minimal_model()))
    assert any(
        i.severity is Severity.WARNING and "no effects declared" in i.message for i in issues
    )


def test_commit_without_verification_is_flagged() -> None:
    save = {"id": "save", "intent": "Save", "action": "click", "target": {"label": "Save"}}
    model = ProcessModel.model_validate(with_steps({**save, "risk": "commit"}, effects=[EFFECT]))
    messages = _messages(model)
    assert any("'commit' step, but no effect is verified" in m for m in messages)
    assert any("effects (saved): never verified" in m for m in messages)


def test_irreversible_step_must_not_fall_back_to_agent() -> None:
    send = {
        "id": "send",
        "intent": "Send the invoice",
        "action": "click",
        "target": {"label": "Send"},
        "risk": "irreversible",
        "fallback": "agent",
        "expect": {"url": "/sent"},
        "verify_effects": ["saved"],
    }
    model = ProcessModel.model_validate(with_steps(send, effects=[EFFECT]))
    assert any("never performs an irreversible step alone" in m for m in _messages(model))


def test_unused_inputs_and_unreferenced_parts() -> None:
    model = ProcessModel.model_validate(
        minimal_model(
            inputs={"cpn": {"type": "string"}, "spare": {"type": "string"}},
            states={"home": {"url": "/"}},
            exceptions={"never": {"kind": "business", "description": "Unused"}},
        )
    )
    messages = _messages(model)
    assert "warning: inputs (spare): never used" in messages
    assert "info: states (home): never referenced" in messages
    assert "info: exceptions (never): never raised by any step" in messages


def test_click_without_postcondition_is_noted() -> None:
    click = {"id": "go", "intent": "Go", "action": "click", "target": {"label": "Go"}}
    model = ProcessModel.model_validate(with_steps(click))
    assert any(i.severity is Severity.INFO and "no 'expect'" in i.message for i in lint(model))
