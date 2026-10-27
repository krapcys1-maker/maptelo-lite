"""Soft checks: the model is valid, but something will hurt at run time."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from maptelo.model.integrity import predicate_values, typed_inputs, value_refs, verified_inputs
from maptelo.model.schema import Action, Executor, ProcessModel, RiskClass


class Severity(StrEnum):
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class LintIssue:
    severity: Severity
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity}: {self.where}: {self.message}"


def lint(model: ProcessModel) -> list[LintIssue]:
    issues: list[LintIssue] = []

    def warn(where: str, message: str) -> None:
        issues.append(LintIssue(Severity.WARNING, where, message))

    def info(where: str, message: str) -> None:
        issues.append(LintIssue(Severity.INFO, where, message))

    if not model.effects:
        warn("effects", "no effects declared: nothing defines 'done', so no run can be VERIFIED")
    verified = {e for s in model.steps for e in s.verify_effects}
    for effect in model.effects:
        if effect.id not in verified:
            warn(f"effects ({effect.id})", "never verified: add it to verify_effects of a step")

    for idx, step in enumerate(model.steps):
        where = f"steps[{idx}] ({step.id})"
        risk = step.effective_risk
        if risk in (RiskClass.COMMIT, RiskClass.IRREVERSIBLE) and not any(
            later.verify_effects for later in model.steps[idx:]
        ):
            warn(where, f"'{risk}' step, but no effect is verified at or after it")
        if risk is RiskClass.IRREVERSIBLE and Executor.AGENT in (step.executor, step.fallback):
            warn(where, "an agent never performs an irreversible step alone; use fallback: human")
        if step.action is Action.CLICK and step.expect is None and step.outcomes is None:
            info(where, "no 'expect' or 'outcomes': drift is noticed only by later steps")

    unchecked = typed_inputs(model.steps) - verified_inputs(model.effects)
    if model.effects and unchecked:
        info(
            "effects",
            "the process types values no effect reads back: "
            f"{', '.join(sorted(unchecked))} (VERIFIED does not cover them)",
        )

    used_inputs = _used_inputs(model)
    for name in model.inputs:
        if name not in used_inputs:
            warn(f"inputs ({name})", "never used")

    used_states = {s.in_state for s in model.steps if s.in_state is not None}
    used_states |= {p.state for s in model.steps for p in s.predicates() if p.state is not None}
    used_states |= {p.state for i in model.interrupts for p in i.when.walk() if p.state is not None}
    for name in model.states:
        if name not in used_states:
            info(f"states ({name})", "never referenced")

    raised = {
        h.raise_ for s in model.steps for h in (s.on_outcome or {}).values() if h.raise_ is not None
    }
    for name in model.exceptions:
        if name not in raised:
            info(f"exceptions ({name})", "never raised by any step")
    return issues


def _used_inputs(model: ProcessModel) -> set[str]:
    values: list[object] = []
    for step in model.steps:
        values.append(step.value)
        if step.within is not None:
            values.extend(step.within.where.values())
            values.extend(step.within.where_not.values())
        for predicate in step.predicates():
            values.extend(predicate_values(predicate))
    for effect in model.effects:
        values.extend(effect.verifier.values())
    for interrupt in model.interrupts:
        values.extend(a.value for a in interrupt.do)
    used = {name for v in values for ns, name in value_refs(v) if ns == "inputs"}
    # the date another is counted from (the rate's day from the day the service was done)
    return used | {
        spec.derived.from_
        for name, spec in model.inputs.items()
        if name in used and spec.derived is not None
    }
