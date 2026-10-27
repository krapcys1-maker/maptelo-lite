"""Referential integrity of a process model: every reference must resolve.

Broken references are errors (the model is rejected). Softer problems live in ``lint.py``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from maptelo.model.schema import Effect, Predicate, ProcessModel, Step

WHOLE_REF = re.compile(r"^\$(inputs|vars)\.([a-z][a-z0-9_]*)$")
PLACEHOLDER = re.compile(r"\{(inputs|vars)\.([a-z][a-z0-9_]*)\}")
_LOOSE_REF = re.compile(r"\$(inputs|vars)\.")


def lines_named(effect: Effect, lines: set[str]) -> bool:
    """A screen's check whose row is named by values of the record's lines (an order's line
    by its number): one row for each line, each line's values compared in its own row."""
    verifier = effect.verifier
    return verifier.kind == "screen" and any(
        space == "inputs" and name in lines
        for value in verifier.row.values()
        for space, name in value_refs(value)
    )


def value_refs(value: object) -> list[tuple[str, str]]:
    """(namespace, name) pairs used by a value: ``$inputs.x`` or ``{inputs.x}`` in text."""
    if not isinstance(value, str):
        return []
    whole = WHOLE_REF.match(value)
    if whole:
        return [(whole.group(1), whole.group(2))]
    return [(m.group(1), m.group(2)) for m in PLACEHOLDER.finditer(value)]


def result_reads(steps: Sequence[Any]) -> list[str]:
    """The values a process reads as its result: read (``save_as``) and used by no step, not
    even to decide (a value read for a later step, the reason a check failed, is no result)."""

    def refs(value: object) -> set[tuple[str, str]]:
        if isinstance(value, dict):
            return set().union(*(refs(v) for v in value.values()))
        if isinstance(value, list):
            return set().union(*(refs(v) for v in value))
        return set(value_refs(value))

    dumped = [s.model_dump(exclude_none=True, mode="json") for s in steps]
    used = {name for space, name in refs(dumped) if space == "vars"}
    return sorted(
        {
            str(step["save_as"])
            for step in dumped
            if step.get("action") == "read" and step.get("save_as")
        }
        - used
    )


_TYPES_IN = {"fill", "select_option", "check", "uncheck", "upload", "pick_date", "choose"}
"""Actions that put a value into the application."""


def _refs_in(value: object) -> set[tuple[str, str]]:
    if isinstance(value, dict):
        return set().union(*(_refs_in(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(_refs_in(v) for v in value))
    return set(value_refs(value))


def typed_inputs(steps: Sequence[Any]) -> set[str]:
    """The inputs the steps put into the application (typed, chosen, ticked, attached)."""
    return {
        name
        for step in steps
        if str(getattr(getattr(step, "action", None), "value", "")) in _TYPES_IN
        for space, name in value_refs(step.value)
        if space == "inputs"
    }


def verified_inputs(effects: Sequence[Any]) -> set[str]:
    """The inputs the effects' independent reads compare (or find the record by)."""
    dumped = [e.model_dump(exclude_none=True, mode="json").get("verifier") for e in effects]
    return {name for space, name in _refs_in(dumped) if space == "inputs"}


def misplaced_ref(value: object) -> bool:
    """``$inputs.x`` inside a longer string, where it would silently be taken literally."""
    return isinstance(value, str) and not WHOLE_REF.match(value) and bool(_LOOSE_REF.search(value))


def predicate_values(predicate: Predicate) -> list[object]:
    """Values compared by a single (non-nested) predicate."""
    values: list[object] = []
    if predicate.field is not None:
        values.append(predicate.field.equals)
    if predicate.value is not None:
        values.append(predicate.value.of)
    if predicate.rows is not None:
        values.extend(predicate.rows.where.values())
    return values


def find_integrity_issues(model: ProcessModel) -> list[str]:
    return list(_issues(model))


def _duplicates(ids: Iterable[str]) -> list[str]:
    return sorted(i for i, n in Counter(ids).items() if n > 1)


def _issues(model: ProcessModel) -> Iterator[str]:
    step_ids = [s.id for s in model.steps]
    for kind, ids in (
        ("steps", step_ids),
        ("effects", [e.id for e in model.effects]),
        ("interrupts", [i.id for i in model.interrupts]),
    ):
        for dup in _duplicates(ids):
            yield f"{kind}: id '{dup}' is used more than once"

    for name, spec in model.inputs.items():
        if spec.derived is None:
            continue
        base = model.inputs.get(spec.derived.from_)
        if base is None:
            yield f"inputs.{name}: counted from unknown input '{spec.derived.from_}'"
        elif base.type.value != "date" or base.derived is not None or base.per_line:
            yield (
                f"inputs.{name}: counted from '{spec.derived.from_}', which is not one date "
                "the record gives"
            )

    lines = {name for name, spec in model.inputs.items() if spec.per_line}
    for idx, step in enumerate(model.steps):
        if step.per_line:
            continue
        used = [n for v in _step_values(step) for space, n in value_refs(v) if space == "inputs"]
        for name in sorted(set(used) & lines):
            yield (
                f"steps[{idx}] ({step.id}): the value of one line '{name}' is only for steps "
                "done for each line (per_line)"
            )
    effect_ids = {e.id for e in model.effects}
    for idx, effect in enumerate(model.effects):
        checked: list[object] = effect.verifier.values()
        yield from _check_values(f"effects[{idx}] ({effect.id})", checked, model, set(), False)
        if lines_named(effect, lines):
            continue  # a screen's row for each line, named by the line's values
        for name in sorted({n for v in checked for _, n in value_refs(v)} & lines):
            yield (
                f"effects[{idx}] ({effect.id}): checks the whole record, not the value of one "
                f"line '{name}'"
            )

    if model.idempotency is not None:
        for ref in model.idempotency.skip_if_effects:
            if ref not in effect_ids:
                yield f"idempotency: unknown effect '{ref}'"

    for idx, interrupt in enumerate(model.interrupts):
        where = f"interrupts[{idx}] ({interrupt.id})"
        yield from _check_predicates(where, interrupt.when.walk(), model, set(), False)
        yield from _check_values(where, [a.value for a in interrupt.do], model, set(), False)

    defined_vars: set[str] = set()
    known_steps = set(step_ids)
    for idx, step in enumerate(model.steps):
        where = f"steps[{idx}] ({step.id})"
        if step.in_state is not None and step.in_state not in model.states:
            yield f"{where}: unknown state '{step.in_state}'"
        yield from _check_predicates(where, step.predicates(), model, defined_vars, True)
        values: list[object] = [step.value]
        if step.within is not None:
            values.extend(step.within.where.values())
            values.extend(step.within.where_not.values())
        for rung in step.target or []:  # a field named by the record's value
            values.extend(
                text
                for key in ("name", "label", "text", "placeholder", "column")
                if isinstance(text := getattr(rung, key, None), str) and "{" in text
            )
        yield from _check_values(where, values, model, defined_vars, True)
        if step.undo is not None:  # read before anything of the record is read on a screen
            undone: list[object] = step.undo.empty.values()
            yield from _check_values(f"{where} undo", undone, model, set(), False)
        if step.find is not None:  # read and opened with the record's own values
            found: list[object] = [
                *step.find.read.values(),
                step.find.list,
                *step.find.row.where.values(),
            ]
            yield from _check_values(f"{where} find", found, model, set(), False)
        for outcome, handler in (step.on_outcome or {}).items():
            if handler.raise_ is not None and handler.raise_ not in model.exceptions:
                yield f"{where}: outcome '{outcome}' raises unknown exception '{handler.raise_}'"
            if handler.goto is not None and handler.goto not in known_steps:
                yield f"{where}: outcome '{outcome}' jumps to unknown step '{handler.goto}'"
            elif handler.goto == step.id:
                yield f"{where}: outcome '{outcome}' jumps to its own step"
        for ref in step.verify_effects:
            if ref not in effect_ids:
                yield f"{where}: unknown effect '{ref}' in verify_effects"
        if step.otherwise is not None and step.otherwise not in step_ids[:idx]:
            yield f"{where}: 'otherwise' names '{step.otherwise}', which is no earlier step"
        if step.save_as is not None:
            defined_vars.add(step.save_as)


def inputs_for_a_person(model: ProcessModel) -> set[str]:
    """Inputs only steps a person makes use (a one-time code, quantities counted on the
    spot): the robot never types them, so a run needs no value for them and a sheet no
    column."""
    by_robot: set[str] = set()
    by_person: set[str] = set()
    for step in model.steps:
        used = {n for v in _step_values(step) for space, n in value_refs(v) if space == "inputs"}
        (by_person if step.executor.value == "human" else by_robot).update(used)
    for effect in model.effects:
        checked: list[object] = effect.verifier.values()
        by_robot.update(n for v in checked for space, n in value_refs(v) if space == "inputs")
    for interrupt in model.interrupts:
        for handler in interrupt.do:
            by_robot.update(n for space, n in value_refs(handler.value) if space == "inputs")
    return by_person - by_robot


def _step_values(step: Step) -> list[object]:
    """Every value a step uses: what it types, its row rule, its conditions."""
    values: list[object] = [step.value]
    if step.within is not None:
        values.extend(step.within.where.values())
        values.extend(step.within.where_not.values())
    for predicate in step.predicates():
        values.extend(predicate_values(predicate))
    return values


def _check_predicates(
    where: str,
    predicates: Iterable[Predicate],
    model: ProcessModel,
    defined_vars: set[str],
    allow_vars: bool,
) -> Iterator[str]:
    for predicate in predicates:
        if predicate.state is not None and predicate.state not in model.states:
            yield f"{where}: unknown state '{predicate.state}'"
        yield from _check_values(
            where, predicate_values(predicate), model, defined_vars, allow_vars
        )


def _check_values(
    where: str,
    values: Iterable[object],
    model: ProcessModel,
    defined_vars: set[str],
    allow_vars: bool,
) -> Iterator[str]:
    for value in values:
        if misplaced_ref(value):
            yield (
                f"{where}: '{value}' has a $-reference inside text; "
                "use {inputs.name} placeholders there"
            )
        for namespace, name in value_refs(value):
            if namespace == "inputs":
                if name not in model.inputs:
                    yield f"{where}: unknown input '{name}'"
            elif not allow_vars:
                yield (
                    f"{where}: may only use inputs, not '$vars.{name}' "
                    "(verification must not depend on what the screen showed)"
                )
            elif name not in defined_vars:
                yield f"{where}: variable '{name}' is used before a 'read' step sets it"
