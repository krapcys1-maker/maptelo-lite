"""A one-file HTML report of a process map: what a person opens to review the mapping."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape

from maptelo import PRODUCT, __version__
from maptelo.export.describe import (
    documented,
    evidence_note,
    input_source,
    predicate_text,
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
from maptelo.export.mermaid import render_mermaid
from maptelo.export.svg import render_svg
from maptelo.mapping.naming import Lang
from maptelo.model.lint import LintIssue
from maptelo.model.schema import Action, Executor, ProcessModel, RiskClass, Step

_STYLE = """
:root { --ink:#232b32; --muted:#59626a; --line:#e5ddd0; --bg:#fbf8f3; --card:#fff;
  --teal:#01687a; --teal-soft:#dcf0f2; --warn-bg:#faedd5; --warn:#8a520b; --err:#a8322b; }
* { box-sizing: border-box; }
body { margin:0; font:15px/1.5 "Segoe UI", system-ui, sans-serif; color:var(--ink);
  background:var(--bg); }
header { background:#232b32; color:#fbf8f3; padding:24px 32px; border-bottom:5px solid #01687a;
  border-image:linear-gradient(90deg, #01687a 0 33.4%, #02b6c0 0 66.7%, #ee9f40 0) 1; }
header .brand { color:#4cc9d1; font-weight:700; letter-spacing:.14em; font-size:12px; }
header h1 { margin:4px 0; font:600 28px/1.2 Georgia, "Iowan Old Style", serif; }
header .meta { color:#c9d1d6; margin:0; }
main { max-width:1100px; margin:0 auto; padding:24px 20px 60px; }
section { background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:18px 22px; margin:18px 0; overflow-x:auto; }
h2 { font-size:18px; margin:0 0 12px; }
.cards { display:flex; gap:12px; flex-wrap:wrap; background:none; border:none; padding:0; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:12px 18px; min-width:130px; }
.card b { display:block; font-size:24px; }
.card span { color:var(--muted); font-size:13px; }
table { border-collapse:collapse; width:100%; }
th, td { border-bottom:1px solid var(--line); padding:7px 8px; text-align:left;
  vertical-align:top; }
code { background:#f1ece3; padding:1px 5px; border-radius:4px; font-size:13px; }
ol.steps { padding-left:22px; margin:0; }
ol.steps > li { padding:10px 0; border-bottom:1px solid var(--line); }
ol.steps > li:last-child { border-bottom:none; }
.intent { font-weight:600; }
.badge { display:inline-block; font-size:12px; padding:1px 8px; border-radius:10px;
  margin-left:6px; background:var(--teal-soft); color:var(--teal); }
.detail { color:var(--muted); margin:4px 0 0; }
.reject { color:var(--err); }
.note { background:var(--warn-bg); color:var(--warn); padding:4px 8px; border-radius:4px;
  margin-top:6px; }
.shot { margin-top:8px; max-width:100%; border:1px solid var(--line); border-radius:6px; }
pre.yaml { background:#142027; color:#e9eef0; padding:14px; border-radius:8px;
  overflow:auto; font-size:12px; }
.diagram { overflow-x:auto; }
.diagram svg { display:block; max-width:100%; height:auto; margin:0 auto; }
summary { cursor:pointer; color:var(--muted); font-size:13px; margin-top:10px; }
footer { color:var(--muted); text-align:center; font-size:13px; }
"""


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def _section(title: str, body: str, css: str = "") -> str:
    attribute = f' class="{css}"' if css else ""
    return f"<section{attribute}><h2>{title}</h2>{body}</section>"


def _items(texts: Sequence[str]) -> str:
    return "<ul>" + "".join(f"<li>{t}</li>" for t in texts) + "</ul>"


def _step_html(step: Step, model: ProcessModel, lang: Lang, image: str | None) -> str:
    def w(key: str) -> str:
        return escape(word(lang, key))

    badge = ""
    if step.effective_risk in (RiskClass.COMMIT, RiskClass.IRREVERSIBLE):
        badge = f'<span class="badge">⚑ {w("commits")}</span>'
    if step.executor is Executor.HUMAN:
        badge += f' <span class="badge">{w("by_person")}</span>'
    details = []
    if step.control:
        details.append(w("control"))
    if (
        step.action is Action.NAVIGATE
        and isinstance(step.value, str)
        and model.application.kind != "java"  # a program is opened, not an address
    ):
        details.append(f"{w('address')}: <code>{escape(step.value)}</code>")
    value = step_value(step)
    if value:
        details.append(f"{w('value')}: <code>{escape(value)}</code>")
    read_at = read_in(step, model)
    if read_at is not None:
        source = "named_in_step" if step.match == "words" else "read_in_step"
        details.append(f"{w('value')}: {w(source)} {read_at}")
    if step.when is not None:
        details.append(f"{w('only_if')}: {escape(predicate_text(step.when, model, lang))}")
    if step.requires is not None:
        shown = escape(predicate_text(step.requires, model, lang))
        details.append(f"{w('requires')}: {shown}; {w('or_stop')}")
    details += [escape(text) for text in window_texts(step, model, lang)]
    if step.no_suggestion == "keep_typed":
        details.append(w("keep_typed"))
    success = step_success(step, model, lang)
    if success:
        details.append(f"{w('expected')}: {escape(success)}")
    for other in step_alternatives(step, model, lang):
        details.append(f"{w('or_else')}: {escape(other)}")
    body = "".join(f'<p class="detail">{d}</p>' for d in details)
    for exception_id, description in step_rejections(step, model):
        body += (
            f'<p class="detail reject">{escape(rejection_lead(step, exception_id, lang))} '
            f"<i>{escape(description)}</i> "
            f"→ {w('then_stop')} (<code>{escape(exception_id)}</code>)</p>"
        )
    note = evidence_note(step, lang)
    if note:
        body += f'<div class="note">{escape(note)}</div>'
    if image:
        body += f'<img class="shot" src="{escape(image)}" alt="{escape(step.intent)}">'
    return f'<li><span class="intent">{escape(step.intent)}</span>{badge}{body}</li>'


def render_html(
    model: ProcessModel,
    *,
    lang: Lang = "pl",
    notes: Sequence[str] = (),
    issues: Sequence[LintIssue] = (),
    images: Mapping[str, str] | None = None,
    source: str | None = None,
    sources: bool = False,
    yaml_text: str | None = None,
) -> str:
    images = images or {}
    model = documented(model)

    def w(key: str) -> str:
        return escape(word(lang, key))

    title = escape(model.title)
    meta = [
        f"{w('process')}: {escape(model.id)}, {w('version')} {model.version}",
        f"{w('application')}: {escape(model.application.name)}",
    ]
    if source:
        meta.append(f"{w('sources' if sources else 'source')}: {escape(source)}")
    parts = [
        "<!doctype html>",
        f'<html lang="{lang}"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title} · {escape(PRODUCT)}</title><style>{_STYLE}</style></head><body>",
        f'<header><div class="brand">{escape(PRODUCT.upper())}</div><h1>{title}</h1>'
        f'<p class="meta">{" · ".join(meta)}</p></header>',
        "<main>",
    ]
    if model.description:
        parts.append(f"<section><p>{escape(model.description)}</p></section>")

    counts = [
        (len(model.steps), w("steps")),
        (len(model.inputs), w("inputs")),
        (len(model.exceptions), w("exceptions")),
        (len(model.interrupts), w("interrupts").split(" (")[0]),
        (len(notes), w("to_confirm")),
    ]
    cards = "".join(
        f'<div class="card"><b>{n}</b><span>{label}</span></div>' for n, label in counts
    )
    parts.append(f'<section class="cards">{cards}</section>')

    # Drawn here, as SVG: the report needs no script and no internet (company networks
    # often block both). The Mermaid text stays below it, for tools that draw Mermaid.
    mermaid = escape(render_mermaid(model, lang=lang))
    as_text = "Diagram jako tekst Mermaid" if lang == "pl" else "The diagram as Mermaid text"
    parts.append(
        _section(
            w("diagram"),
            f'<div class="diagram">{render_svg(model, lang=lang)}</div>'
            f'<details><summary>{as_text}</summary><pre class="yaml">{mermaid}</pre></details>',
        )
    )

    if model.preconditions:
        parts.append(_section(w("preconditions"), _items([escape(p) for p in model.preconditions])))

    if model.inputs:
        sourced = any(s.column for s in model.inputs.values())
        rows = [
            [
                f"<code>{escape(name)}</code>",
                escape(type_name(lang, spec.type)),
                escape(spec.description or ""),
                escape("" if spec.example is None else str(spec.example)),
                *([escape(input_source(spec, lang))] if sourced else []),
            ]
            for name, spec in model.inputs.items()
        ]
        headers = [w("input"), w("type"), w("description"), w("example")]
        headers += [w("source_column")] if sourced else []
        per_row = records_text(model, lang)
        lead = f"<p>{escape(per_row)}</p>" if per_row else ""
        parts.append(_section(w("inputs"), lead + _table(headers, rows)))

    steps = "".join(_step_html(s, model, lang, images.get(s.id)) for s in model.steps)
    parts.append(_section(w("steps"), f'<ol class="steps">{steps}</ol>'))

    if model.exceptions:
        rows = [
            [
                f"<code>{escape(exception_id)}</code>",
                w(spec.kind.value),
                escape(spec.description),
                w("retry") if spec.is_retryable else w("stop_and_report"),
            ]
            for exception_id, spec in model.exceptions.items()
        ]
        headers = [w("exception"), w("kind"), w("description"), w("what_to_do")]
        parts.append(_section(w("exceptions"), _table(headers, rows)))

    if model.interrupts:
        texts = []
        for interrupt in model.interrupts:
            buttons = ", ".join(
                escape(a.target[0].name or a.target[0].describe()) for a in interrupt.do if a.target
            )
            texts.append(f"{escape(predicate_text(interrupt.when, model, lang))} → {buttons}")
        parts.append(_section(w("interrupts"), _items(texts)))

    if model.effects:
        effects = [
            f"<b>{escape(e.id)}</b>: {escape(e.description)} "
            f"(<code>{escape(e.verifier.describe())}</code>)"
            for e in model.effects
        ]
    else:
        effects = [f'<span class="note">⚠ {w("no_effects")}</span>']
    parts.append(_section(w("verification"), _items(effects)))

    if notes:
        parts.append(_section(w("to_confirm"), _items([escape(n) for n in notes]), "confirm"))
    if issues:
        parts.append(_section(w("warnings"), _items([escape(str(i)) for i in issues])))
    if yaml_text:
        parts.append(
            f"<section><details><summary>{w('model_source')}</summary>"
            f'<pre class="yaml">{escape(yaml_text)}</pre></details></section>'
        )
    parts.append(
        f"<footer>{w('generated')} {escape(PRODUCT)} {escape(__version__)}</footer></main>"
    )
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"
