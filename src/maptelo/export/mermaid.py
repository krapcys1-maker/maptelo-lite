"""Process diagram as a Mermaid flowchart (renders in GitHub, GitLab, Confluence, Notion)."""

from __future__ import annotations

from maptelo.export.describe import documented, predicate_text, step_rejections, word
from maptelo.mapping.naming import Lang
from maptelo.model.schema import ProcessModel, RiskClass


def _label(text: str) -> str:
    return text.replace('"', "#quot;").replace("\n", " ")


def render_mermaid(model: ProcessModel, *, lang: Lang = "pl") -> str:
    model = documented(model)
    yes, no = ("tak", "nie") if lang == "pl" else ("yes", "no")
    lines = ["flowchart TD", f'    start(["{_label(word(lang, "start"))}"])']
    entry: dict[int, str] = {}
    for number, step in enumerate(model.steps, start=1):
        text = _label(f"{number}. {step.intent}")
        commits = step.effective_risk in (RiskClass.COMMIT, RiskClass.IRREVERSIBLE)
        lines.append(f'    s{number}[["{text}"]]' if commits else f'    s{number}["{text}"]')
        entry[number] = f"s{number}"
        if step.when is not None:
            condition = _label(predicate_text(step.when, model, lang) + "?")
            lines.append(f'    d{number}{{"{condition}"}}')
            entry[number] = f"d{number}"
    lines.append(f'    finish(["{_label(word(lang, "end"))}"])')

    exception_nodes: dict[str, str] = {}
    edges: list[str] = []
    previous = "start"
    for number, step in enumerate(model.steps, start=1):
        edges.append(f"    {previous} --> {entry[number]}")
        if step.when is not None:
            edges.append(f"    d{number} -->|{yes}| s{number}")
            edges.append(f"    d{number} -->|{no}| {entry.get(number + 1, 'finish')}")
        for exception_id, description in step_rejections(step, model):
            if exception_id not in exception_nodes:
                node = f"e{len(exception_nodes) + 1}"
                exception_nodes[exception_id] = node
                lines.append(f'    {node}(["{_label(description)}"])')
            edges.append(f"    s{number} -.->|{exception_id}| {exception_nodes[exception_id]}")
        previous = f"s{number}"
    edges.append(f"    {previous} --> finish")
    lines += edges

    for number, interrupt in enumerate(model.interrupts, start=1):
        what = _label(predicate_text(interrupt.when, model, lang))
        lines.append(f'    i{number}{{{{"⚡ {what}"}}}}')
    if exception_nodes:
        lines.append("    classDef exception fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d")
        lines.append(f"    class {','.join(exception_nodes.values())} exception")
    if model.interrupts:
        lines.append("    classDef interrupt fill:#fef3c7,stroke:#b45309,color:#78350f")
        names = ",".join(f"i{n}" for n in range(1, len(model.interrupts) + 1))
        lines.append(f"    class {names} interrupt")
    return "\n".join(lines) + "\n"
