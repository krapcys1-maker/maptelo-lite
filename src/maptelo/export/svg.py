"""The process diagram as a self-contained SVG: no script, no internet, the same in a report
opened on a company computer, in a document and in Studio.

Top to bottom: start, the steps (a step that saves has a heavier frame and a tag), a diamond
before a step that runs only on a condition (its "no" goes round the step on the left), the
known rejections of a step to its right (dashed), the end; what can interrupt at any time
sits under the end. The Mermaid export says the same for tools that draw Mermaid.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

from maptelo.export.describe import documented, predicate_text, step_rejections, word
from maptelo.mapping.naming import Lang
from maptelo.model.schema import ProcessModel, RiskClass

NODE_W = 300
SIDE_W = 220
LANE = 56
"""Room on the left for the "no" of a condition."""
GAP = 30
LINE = 17
PAD = 11
MARGIN = 16
CHARS = 40
SIDE_CHARS = 28

_RULES = """
.n rect, .n path { stroke-width: 1.4; }
.step rect { fill: #ffffff; stroke: #7c858c; }
.write rect { fill: #dcf0f2; stroke: #01687a; stroke-width: 2.4; }
.write .tag { fill: #01687a; font-size: 10px; font-weight: 700; letter-spacing: .06em; }
.ends rect { fill: #232b32; stroke: #232b32; }
.ends text { fill: #ffffff; font-weight: 600; }
.cond path { fill: #fbf8f3; stroke: #7c858c; }
.rejected rect { fill: #fee2e2; stroke: #b91c1c; }
.rejected text { fill: #7f1d1d; }
.interrupt rect { fill: #fef3c7; stroke: #b45309; }
.interrupt text { fill: #78350f; }
text { font: 13px "Segoe UI", system-ui, sans-serif; fill: #232b32; }
.num { font-weight: 700; }
.edge { fill: none; stroke: #59626a; stroke-width: 1.4; }
.edge.dash { stroke: #b91c1c; stroke-dasharray: 5 4; }
.label { font-size: 11px; fill: #59626a; }
.rejected .code { font: 11px "Cascadia Mono", Consolas, monospace; fill: #b91c1c; }
.head { font-size: 11px; font-weight: 700; letter-spacing: .08em; fill: #6e7780; }
"""
SCOPE = "svg.maptelo-diagram"


def _scoped(rules: str) -> str:
    """Every rule only for the diagram: drawn into a page (the report), its styles would
    otherwise reach the page's own elements of the same class."""
    lines = []
    for rule in rules.strip().splitlines():
        selectors, _, body = rule.partition("{")
        lines.append(", ".join(f"{SCOPE} {s.strip()}" for s in selectors.split(",")) + " {" + body)
    return "\n".join(lines)


STYLE = _scoped(_RULES)


def wrap(text: str, width: int) -> list[str]:
    """Words into lines of at most ``width`` characters (a longer word is cut)."""
    lines: list[str] = []
    current = ""
    for word_ in text.split():
        while len(word_) > width:
            if current:
                lines.append(current)
                current = ""
            lines.append(word_[: width - 1] + "-")
            word_ = word_[width - 1 :]
        if not current:
            current = word_
        elif len(current) + 1 + len(word_) <= width:
            current += " " + word_
        else:
            lines.append(current)
            current = word_
    if current:
        lines.append(current)
    return lines or [""]


@dataclass
class _Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def top(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y

    @property
    def bottom(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h

    @property
    def left(self) -> tuple[float, float]:
        return self.x, self.y + self.h / 2

    @property
    def right(self) -> tuple[float, float]:
        return self.x + self.w, self.y + self.h / 2


def _text(lines: list[str], cx: float, top: float, cls: str = "") -> str:
    attr = f' class="{cls}"' if cls else ""
    spans = "".join(
        f'<tspan x="{cx:.1f}" y="{top + PAD + LINE * (i + 0.8):.1f}">{escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return f'<text text-anchor="middle"{attr}>{spans}</text>'


def _arrow(points: list[tuple[float, float]], cls: str = "edge") -> str:
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(points))
    return f'<path class="{cls}" d="{path}" marker-end="url(#maptelo-arrow)"/>'


def render_svg(model: ProcessModel, *, lang: Lang = "pl") -> str:
    model = documented(model)
    yes, no = ("tak", "nie") if lang == "pl" else ("yes", "no")
    writes_tag = "ZAPISUJE" if lang == "pl" else "SAVES"
    left = MARGIN + LANE
    cx = left + NODE_W / 2
    side_x = left + NODE_W + 70
    shapes: list[str] = []
    edges: list[str] = []
    y: float = MARGIN

    def pill(label: str) -> _Box:
        nonlocal y
        box = _Box(cx - 70, y, 140, 36)
        shapes.append(
            f'<g class="n ends"><rect x="{box.x}" y="{box.y}" width="{box.w}" height="{box.h}"'
            f' rx="18"/>{_text([label], cx, box.y - 2)}</g>'
        )
        y += box.h + GAP
        return box

    start = pill(word(lang, "start"))
    previous = start
    pending_no: tuple[float, float] | None = None
    """Where the "no" of the last condition leaves, to land on the next entry."""
    side_bottom = 0.0

    def land(target: _Box) -> None:
        nonlocal pending_no
        if pending_no is not None:
            x0, y0 = pending_no
            lane = MARGIN + LANE / 3
            ty = target.y - 10
            edges.append(
                _arrow([(x0, y0), (lane, y0), (lane, ty), (target.top[0], ty), target.top])
            )
            pending_no = None

    for number, step in enumerate(model.steps, start=1):
        if step.when is not None:
            condition = wrap(predicate_text(step.when, model, lang) + "?", CHARS - 12)
            h = max(64, len(condition) * LINE + 2 * PAD + 18)
            diamond = _Box(cx - NODE_W / 2, y, NODE_W, h)
            shapes.append(
                f'<g class="n cond"><path d="M{cx},{diamond.y} L{diamond.x + diamond.w},'
                f'{diamond.y + h / 2} L{cx},{diamond.y + h} L{diamond.x},{diamond.y + h / 2} Z"/>'
                f"{_text(condition, cx, diamond.y + h / 2 - len(condition) * LINE / 2 - PAD)}</g>"
            )
            edges.append(_arrow([previous.bottom, diamond.top]))
            land(diamond)
            edges.append(f'<text class="label" x="{cx + 6}" y="{diamond.y + h + 14}">{yes}</text>')
            edges.append(
                f'<text class="label" x="{diamond.x - 22}" y="{diamond.y + h / 2 - 5}">{no}</text>'
            )
            y += h + GAP
            entry_from = diamond
        else:
            entry_from = previous
        writes = step.effective_risk in (RiskClass.COMMIT, RiskClass.IRREVERSIBLE)
        lines = wrap(f"{number}. {step.intent}", CHARS)
        h = len(lines) * LINE + 2 * PAD + (10 if writes else 0)
        box = _Box(left, y, NODE_W, h)
        cls = "n step write" if writes else "n step"
        tag = (
            f'<text class="tag" x="{box.x + box.w - 8}" y="{box.y + 13}" text-anchor="end">'
            f"{writes_tag}</text>"
            if writes
            else ""
        )
        shapes.append(
            f'<g class="{cls}"><rect x="{box.x}" y="{box.y}" width="{box.w}" height="{box.h}"'
            f' rx="6"/>{tag}{_text(lines, cx, box.y + (10 if writes else 0))}</g>'
        )
        edges.append(_arrow([entry_from.bottom, box.top]))
        if step.when is None:
            land(box)
        else:
            pending_no = (entry_from.left[0], entry_from.left[1])
        side_y = max(box.y, side_bottom)
        for exception_id, description in step_rejections(step, model):
            text = wrap(description, SIDE_CHARS)
            sh = len(text) * LINE + 2 * PAD + LINE  # and the exception's name, small
            side = _Box(side_x, side_y, SIDE_W, sh)
            shapes.append(
                f'<g class="n rejected"><rect x="{side.x}" y="{side.y}" width="{side.w}"'
                f' height="{side.h}" rx="12"/>{_text(text, side.x + side.w / 2, side.y)}'
                f'<text class="code" text-anchor="middle" x="{side.x + side.w / 2:.1f}"'
                f' y="{side.y + side.h - PAD + 2:.1f}">{escape(exception_id)}</text></g>'
            )
            start_point = box.right
            edges.append(
                _arrow(
                    [
                        start_point,
                        (side_x - 30, start_point[1]),
                        (side_x - 30, side.left[1]),
                        side.left,
                    ],
                    "edge dash",
                )
            )
            side_y += sh + 10
            side_bottom = side_y
        y = max(y + h + GAP, side_bottom)
        previous = box

    finish = pill(word(lang, "end"))
    edges.append(_arrow([previous.bottom, finish.top]))
    land(finish)

    if model.interrupts:
        shapes.append(
            f'<text class="head" x="{left}" y="{y + 4}">'
            f"{'W KAŻDEJ CHWILI' if lang == 'pl' else 'AT ANY TIME'}</text>"
        )
        y += 16
        for interrupt in model.interrupts:
            text = wrap("⚡ " + predicate_text(interrupt.when, model, lang), CHARS)
            ih = len(text) * LINE + 2 * PAD
            shapes.append(
                f'<g class="n interrupt"><rect x="{left}" y="{y}" width="{NODE_W}" height="{ih}"'
                f' rx="4"/>{_text(text, cx, y)}</g>'
            )
            y += ih + 10
    width = (
        side_x + SIDE_W + MARGIN
        if any(step_rejections(s, model) for s in model.steps)
        else (left + NODE_W + MARGIN)
    )
    height = max(y, side_bottom) + MARGIN
    title = escape(model.title)
    summary = escape(
        f"{word(lang, 'diagram')}: {len(model.steps)} " + ("kroków" if lang == "pl" else "steps")
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="maptelo-diagram"'
        f' viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}"'
        ' role="img" aria-labelledby="maptelo-title maptelo-desc">'
        f'<title id="maptelo-title">{title}</title><desc id="maptelo-desc">{summary}</desc>'
        f"<style>{STYLE}</style>"
        '<defs><marker id="maptelo-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"'
        ' markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z"'
        ' fill="#59626a"/></marker></defs>'
        f"<g>{''.join(edges)}</g><g>{''.join(shapes)}</g></svg>\n"
    )
