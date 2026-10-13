"""Standard operating procedure (SOP) in Markdown: what a person reads to do the process."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from maptelo import PRODUCT, __version__
from maptelo.export.describe import (
    documented,
    evidence_note,
    input_source,
    predicate_text,
    quoted,
    read_in,
    records_text,
    rejection_lead,
    step_alternatives,
    step_rejections,
    step_success,
    step_value,
    type_name,
    window_texts,
    word,
)
from maptelo.mapping.naming import Lang
from maptelo.model.schema import Action, Executor, ProcessModel, RiskClass

_CHECKS = {
    "pl": {
        "nip": "cyfra kontrolna NIP",
        "iban": "suma kontrolna rachunku",
        "date": "poprawna data",
        "amount": "kwota",
        "number": "liczba",
        "code": "pewny odczyt",
        "text": "pewny odczyt",
        "sum": ", netto + VAT = brutto",
    },
    "en": {
        "nip": "the tax number's check digit",
        "iban": "the account's checksum",
        "date": "a real date",
        "amount": "an amount",
        "number": "a number",
        "code": "a sure reading",
        "text": "a sure reading",
        "sum": ", net + VAT = gross",
    },
}
"""What the rules check in a value read from a document's picture, by its kind."""


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_sop(
    model: ProcessModel,
    *,
    lang: Lang = "pl",
    notes: Sequence[str] = (),
    images: Mapping[str, str] | None = None,
    source: str | None = None,
    sources: bool = False,
) -> str:
    """``source``: the recording the map is made from („12.10.2026 (20261012T182653Z-f7b7)”);
    ``sources``: it names several."""
    images = images or {}
    model = documented(model)

    def w(key: str) -> str:
        return word(lang, key)

    meta = [
        f"{w('process')}: `{model.id}`, {w('version')} {model.version}",
        f"{w('application')}: {model.application.name}",
    ]
    if source:
        meta.append(f"{w('sources' if sources else 'source')}: {source}")
    out = [f"# {model.title}", "", "*" + " · ".join(meta) + "*", ""]
    if model.description:
        out += [f"> {model.description}", ""]

    if model.preconditions:
        out += [f"## {w('preconditions')}", ""]
        out += [f"- {p}" for p in model.preconditions] + [""]

    if model.inputs:
        out += [f"## {w('inputs')}", ""]
        per_row = records_text(model, lang)
        if per_row:
            out += [per_row, ""]
        sourced = any(s.column or s.derived for s in model.inputs.values())
        head = [w("input"), w("type"), w("description"), w("example")]
        head += [w("source_column")] if sourced else []
        out += ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        for name, spec in model.inputs.items():
            example = "" if spec.example is None else spec.example
            kind = type_name(lang, spec.type)
            kind += f" ({w('per_line_input')})" if spec.per_line else ""
            cells = [f"`{name}`", kind, _cell(spec.description or ""),
                     _cell(example)]  # fmt: skip
            cells += [_cell(input_source(spec, lang))] if sourced else []
            out.append("| " + " | ".join(str(c) for c in cells) + " |")
        out.append("")

    out += [f"## {w('steps')}", ""]
    previous_per_line = False
    java = model.application.kind == "java"  # a program is opened, not an address
    for number, step in enumerate(model.steps, start=1):
        if step.per_line and not previous_per_line:  # a block done for each line
            out += [f"**{w('each_line')}**", ""]
        previous_per_line = step.per_line
        line = f"{number}. {'↻ ' if step.per_line else ''}**{step.intent}**"
        if step.action is Action.NAVIGATE and isinstance(step.value, str) and not java:
            line += f" — {w('address')} `{step.value}`"
        value = step_value(step)
        if value and step.action in (Action.FILL, Action.SELECT_OPTION, Action.PICK_DATE):
            line += f" — {w('value')}: `{value}`"
        read_at = read_in(step, model)
        if step.action is Action.UPLOAD:
            given = f"{w('downloaded_in_step')} {read_at}" if read_at else f"`{value}`"
            line += f" — {w('file')}: {given}"
        elif read_at is not None:
            source = "named_in_step" if step.match == "words" else "read_in_step"
            line += f" — {w('value')}: {w(source)} {read_at}"
        if step.effective_risk in (RiskClass.COMMIT, RiskClass.IRREVERSIBLE):
            line += f" ⚑ *{w('commits')}*"
        if step.executor is Executor.HUMAN:
            line += f" — *{w('by_person')}*"
        out.append(line)
        if step.document is not None:
            checks = _CHECKS[lang if lang in _CHECKS else "en"]
            shown = checks[step.document.kind] + (checks["sum"] if step.document.role else "")
            out.append(f"   - {w('from_picture').format(checks=shown)}")
        if step.control:
            out.append(f"   - {w('control')}")
        if step.otherwise is not None:
            first = next(n for n, s in enumerate(model.steps, start=1) if s.id == step.otherwise)
            out.append(f"   - {w('otherwise').format(step=first)}")
        if step.when is not None:
            out.append(f"   - {w('only_if')}: {predicate_text(step.when, model, lang)}")
        if step.requires is not None:
            shown = predicate_text(step.requires, model, lang)
            out.append(f"   - {w('requires')}: {shown}; {w('or_stop')}")
        out += [f"   - {text}" for text in window_texts(step, model, lang)]
        if step.no_suggestion == "keep_typed":
            out.append(f"   - {w('keep_typed')}")
        success = step_success(step, model, lang)
        if success:
            out.append(f"   - {w('expected')}: {success}")
        for other in step_alternatives(step, model, lang):
            out.append(f"   - {w('or_else')}: {other}")
        for exception_id, description in step_rejections(step, model):
            out.append(
                f"   - {rejection_lead(step, exception_id, lang)} *{description}* → "
                f"{w('then_stop')} (`{exception_id}`)"
            )
        note = evidence_note(step, lang)
        if note:
            out.append(f"   - {note}")
        if step.id in images:
            out += ["", f"   ![{number}. {step.intent}]({images[step.id]})"]
        out.append("")

    if model.exceptions:
        out += [f"## {w('exceptions')}", ""]
        out += [
            f"| {w('exception')} | {w('kind')} | {w('description')} | {w('what_to_do')} |",
            "|---|---|---|---|",
        ]
        for exception_id, exception in model.exceptions.items():
            todo = w("retry") if exception.is_retryable else w("stop_and_report")
            kind = w(exception.kind.value)
            out.append(f"| `{exception_id}` | {kind} | {_cell(exception.description)} | {todo} |")
        out.append("")

    if model.interrupts:
        out += [f"## {w('interrupts')}", ""]
        for interrupt in model.interrupts:
            actions = ", ".join(
                f"{w('click')} {quoted(a.target[0].name or a.target[0].describe(), lang)}"
                if a.target
                else a.action.value
                for a in interrupt.do
            )
            out.append(f"- {predicate_text(interrupt.when, model, lang)} → {actions}")
        out.append("")

    out += [f"## {w('verification')}", ""]
    if model.effects:
        for effect in model.effects:
            out.append(f"- **{effect.id}**: {effect.description} (`{effect.verifier.describe()}`)")
    else:
        out.append(f"- ⚠ {w('no_effects')}")
    out.append("")

    if notes:
        out += [f"## {w('to_confirm')}", ""]
        out += [f"- {note}" for note in notes] + [""]

    out.append(f"*{w('generated')} {PRODUCT} {__version__}.*")
    return "\n".join(out) + "\n"
