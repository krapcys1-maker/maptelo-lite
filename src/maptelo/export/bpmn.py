"""BPMN 2.0 XML with diagram layout, for Signavio, Camunda Modeler, bpmn.io, UiPath Maestro.

The map is an "as is" process: steps are user tasks; a step with known rejections is
followed by an exclusive gateway whose error branches end in error end events.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from itertools import groupby
from xml.sax.saxutils import escape, quoteattr

from maptelo import __version__
from maptelo.export.describe import documented, predicate_text, step_rejections, word
from maptelo.mapping.naming import Lang
from maptelo.model.schema import ProcessModel, Step

TASK_W, TASK_H = 130, 80
EVENT = 36
GATEWAY = 50
GAP = 50
MID_Y = 220


@dataclass
class _Node:
    id: str
    kind: str
    name: str
    x: int
    y: int
    w: int
    h: int
    incoming: list[str] = field(default_factory=list)
    outgoing: list[str] = field(default_factory=list)
    extra: str = ""
    label: tuple[int, int, int, int] | None = None
    """Where the name is drawn (x, y, width, height); None lets the tool decide."""

    @property
    def right(self) -> tuple[int, int]:
        return self.x + self.w, self.y + self.h // 2

    @property
    def left(self) -> tuple[int, int]:
        return self.x, self.y + self.h // 2

    @property
    def bottom(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h

    @property
    def top(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y


@dataclass
class _Flow:
    id: str
    source: _Node
    target: _Node
    name: str = ""
    downward: bool = False
    waypoints: list[tuple[int, int]] | None = None
    """A route around other shapes (e.g. to the second error below one gateway)."""
    label: tuple[int, int, int, int] | None = None


def _label(bounds: tuple[int, int, int, int] | None) -> list[str]:
    if bounds is None:
        return []
    x, y, width, height = bounds
    return [
        "        <bpmndi:BPMNLabel>",
        f'          <dc:Bounds x="{x}" y="{y}" width="{width}" height="{height}" />',
        "        </bpmndi:BPMNLabel>",
    ]


def _xml_id(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in text)


def _loop_body(model: ProcessModel, steps: list[Step], lang: Lang) -> str:
    """A consecutive per-line block repeats as one subprocess, in its original order."""
    inner = model.model_copy(
        update={
            "steps": [s.model_copy(update={"per_line": False}) for s in steps],
            "interrupts": [],
        }
    )
    root = ET.fromstring(render_bpmn(inner, lang=lang))
    ns = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"
    process = root.find(ns + "process")
    assert process is not None
    prefix = f"Line_{_xml_id(steps[0].id)}_"
    ids = {e.attrib["id"]: prefix + e.attrib["id"] for e in process.iter() if "id" in e.attrib}
    for element in process.iter():
        for key in ("id", "sourceRef", "targetRef"):
            if element.get(key) in ids:
                element.set(key, ids[element.attrib[key]])
        if element.tag in (ns + "incoming", ns + "outgoing") and element.text in ids:
            element.text = ids[element.text]
    body = "".join(
        ET.tostring(e, encoding="unicode") for e in process if e.tag != ns + "documentation"
    )
    return '<bpmn:multiInstanceLoopCharacteristics isSequential="true" />' + body


def render_bpmn(model: ProcessModel, *, lang: Lang = "pl") -> str:
    model = documented(model)
    nodes: list[_Node] = []
    flows: list[_Flow] = []
    errors: dict[str, str] = {key: exc.description for key, exc in model.exceptions.items()}

    def connect(
        source: _Node,
        target: _Node,
        name: str = "",
        downward: bool = False,
        waypoints: list[tuple[int, int]] | None = None,
        label: tuple[int, int, int, int] | None = None,
    ) -> None:
        flow = _Flow(f"Flow_{len(flows) + 1}", source, target, name, downward, waypoints, label)
        source.outgoing.append(flow.id)
        target.incoming.append(flow.id)
        flows.append(flow)

    x = 80
    start = _Node(
        "StartEvent_1", "startEvent", word(lang, "start"), x, MID_Y - EVENT // 2, EVENT, EVENT
    )
    nodes.append(start)
    previous = start
    x += EVENT + GAP
    error_row = 0
    rendered: list[tuple[Step, str | None]] = []
    for repeated, group in groupby(model.steps, key=lambda s: s.per_line):
        steps = list(group)
        if repeated:
            loop_label = "Dla każdej pozycji" if lang == "pl" else "For each line"
            virtual = steps[0].model_copy(
                update={"intent": loop_label, "when": None, "on_outcome": None, "outcomes": None}
            )
            rendered.append((virtual, _loop_body(model, steps, lang)))
        else:
            rendered.extend((step, None) for step in steps)
    for number, (step, loop_body) in enumerate(rendered, start=1):
        guard = None
        if step.when is not None:
            guard = _Node(
                f"When_{_xml_id(step.id)}",
                "exclusiveGateway",
                predicate_text(step.when, model, lang),
                x,
                MID_Y - GATEWAY // 2,
                GATEWAY,
                GATEWAY,
                label=(x - 45, MID_Y - 95, 150, 55),
            )
            nodes.append(guard)
            connect(previous, guard)
            previous = guard
            x += GATEWAY + GAP
        docs = escape(f"{step.action.value}: {step.intent}")
        task = _Node(
            f"Task_{_xml_id(step.id)}",
            "subProcess" if loop_body is not None else "userTask",
            f"{number}. {step.intent}",
            x,
            MID_Y - TASK_H // 2,
            TASK_W,
            TASK_H,
            extra=loop_body or f"<bpmn:documentation>{docs}</bpmn:documentation>",
        )
        nodes.append(task)
        connect(previous, task, ("tak" if lang == "pl" else "yes") if guard else "")
        previous = task
        x += TASK_W + GAP
        rejections = step_rejections(step, model)
        if rejections:
            gateway = _Node(
                f"Gateway_{_xml_id(step.id)}",
                "exclusiveGateway",
                word(lang, "result"),
                x,
                MID_Y - GATEWAY // 2,
                GATEWAY,
                GATEWAY,
                label=(x - 15, MID_Y - GATEWAY // 2 - 24, GATEWAY + 30, 16),  # above it
            )
            nodes.append(gateway)
            connect(task, gateway)
            for row, (exception_id, description) in enumerate(rejections):
                errors.setdefault(exception_id, description)
                end = _Node(
                    f"End_{_xml_id(exception_id)}_{number}",
                    "endEvent",
                    description,
                    x + (GATEWAY - EVENT) // 2,
                    MID_Y + 90 + row * 100,
                    EVENT,
                    EVENT,
                    extra=f'<bpmn:errorEventDefinition errorRef="Error_{_xml_id(exception_id)}" />',
                )
                nodes.append(end)
                (cx, by), (ex, ey) = gateway.bottom, end.right
                route = None
                label = (cx - 150, by + 12, 140, 28)  # left of the line down
                if row:  # pass the errors above on their right and come in from the side
                    lane = cx + 60
                    route = [(cx, by), (cx, by + 20), (lane, by + 20), (lane, ey), (ex, ey)]
                    label = (lane + 8, ey - 40, 150, 28)
                connect(gateway, end, exception_id, downward=True, waypoints=route, label=label)
                error_row = max(error_row, row)
            previous = gateway
            x += GATEWAY + GAP
        if guard is not None:
            join = _Node(
                f"Join_{_xml_id(step.id)}",
                "exclusiveGateway",
                "",
                x,
                MID_Y - GATEWAY // 2,
                GATEWAY,
                GATEWAY,
            )
            nodes.append(join)
            connect(previous, join)
            gx, gy = guard.bottom
            jx, jy = join.bottom
            connect(
                guard,
                join,
                "nie" if lang == "pl" else "no",
                waypoints=[(gx, gy), (gx, MID_Y + 70), (jx, MID_Y + 70), (jx, jy)],
            )
            previous = join
            x += GATEWAY + GAP
    finish = _Node("EndEvent_1", "endEvent", word(lang, "end"), x, MID_Y - EVENT // 2, EVENT, EVENT)
    nodes.append(finish)
    connect(previous, finish)

    annotations = [
        (f"Annotation_{_xml_id(i.id)}", f"⚡ {predicate_text(i.when, model, lang)}")
        for i in model.interrupts
    ]

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'
        ' xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"'
        ' xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"'
        ' xmlns:di="http://www.omg.org/spec/DD/20100524/DI"'
        f' id="Definitions_{_xml_id(model.id)}" targetNamespace="urn:maptelo:{model.id}"'
        f' exporter="Maptelo" exporterVersion={quoteattr(__version__)}>',
    ]
    for exception_id, description in errors.items():
        out.append(
            f'  <bpmn:error id="Error_{_xml_id(exception_id)}" name={quoteattr(description)}'
            f" errorCode={quoteattr(exception_id)} />"
        )
    process_id = f"Process_{_xml_id(model.id)}"
    out.append(
        f'  <bpmn:process id="{process_id}" name={quoteattr(model.title)} isExecutable="false">'
    )
    if model.description:
        out.append(f"    <bpmn:documentation>{escape(model.description)}</bpmn:documentation>")
    for node in nodes:
        out.append(f"    <bpmn:{node.kind} id={quoteattr(node.id)} name={quoteattr(node.name)}>")
        if node.extra and node.kind == "userTask":
            out.append(f"      {node.extra}")
        out += [f"      <bpmn:incoming>{f}</bpmn:incoming>" for f in node.incoming]
        out += [f"      <bpmn:outgoing>{f}</bpmn:outgoing>" for f in node.outgoing]
        if node.extra and node.kind != "userTask":
            out.append(f"      {node.extra}")
        out.append(f"    </bpmn:{node.kind}>")
    for flow in flows:
        name = f" name={quoteattr(flow.name)}" if flow.name else ""
        out.append(
            f'    <bpmn:sequenceFlow id="{flow.id}" sourceRef="{flow.source.id}"'
            f' targetRef="{flow.target.id}"{name} />'
        )
    for annotation_id, text in annotations:
        out.append(f'    <bpmn:textAnnotation id="{annotation_id}">')
        out.append(f"      <bpmn:text>{escape(text)}</bpmn:text>")
        out.append("    </bpmn:textAnnotation>")
    out.append("  </bpmn:process>")

    out.append('  <bpmndi:BPMNDiagram id="BPMNDiagram_1">')
    out.append(f'    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="{process_id}">')
    for node in nodes:
        out.append(f'      <bpmndi:BPMNShape id="{node.id}_di" bpmnElement="{node.id}">')
        out.append(
            f'        <dc:Bounds x="{node.x}" y="{node.y}" width="{node.w}" height="{node.h}" />'
        )
        out += _label(node.label)
        out.append("      </bpmndi:BPMNShape>")
    for flow in flows:
        start_point = flow.source.bottom if flow.downward else flow.source.right
        end_point = flow.target.top if flow.downward else flow.target.left
        points = flow.waypoints or [start_point, end_point]
        out.append(f'      <bpmndi:BPMNEdge id="{flow.id}_di" bpmnElement="{flow.id}">')
        for px, py in points:
            out.append(f'        <di:waypoint x="{px}" y="{py}" />')
        out += _label(flow.label)
        out.append("      </bpmndi:BPMNEdge>")
    for index, (annotation_id, _) in enumerate(annotations):
        out.append(
            f'      <bpmndi:BPMNShape id="{annotation_id}_di" bpmnElement="{annotation_id}">'
        )
        out.append(f'        <dc:Bounds x="{80 + index * 260}" y="60" width="240" height="50" />')
        out.append("      </bpmndi:BPMNShape>")
    out.append("    </bpmndi:BPMNPlane>")
    out.append("  </bpmndi:BPMNDiagram>")
    out.append("</bpmn:definitions>")
    return "\n".join(out) + "\n"
