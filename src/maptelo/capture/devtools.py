"""Importing recordings made with the Recorder panel built into Chrome and Edge DevTools.

The exported JSON ("user flow", format of puppeteer/replay, Apache-2.0) has no screen
states, but it needs no installation at all, which matters on locked-down company PCs.
Selectors map onto our locator ladder: aria/ -> role+name or label/text, text/ -> text,
pierce/ and plain CSS -> css (plus test id when the CSS targets the selector attribute).
XPath selectors are dropped.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maptelo.model.schema import Locator
from maptelo.trace.io import TraceWriter
from maptelo.trace.schema import ElementInfo, TraceEnd, TraceEvent, TraceHeader

_ARIA = re.compile(r'^aria/(?P<name>.*?)(?:\[role="(?P<role>[^"]+)"\])?$')
_SKIPPED = {
    "keyUp", "hover", "scroll", "waitForElement", "waitForExpression",
    "emulateNetworkConditions", "close", "customStep",
}  # fmt: skip


class DevToolsImportError(Exception):
    pass


def _testid_css(selector: str, attribute: str) -> str | None:
    match = re.fullmatch(rf"\[{re.escape(attribute)}=['\"]?([^'\"\]]+)['\"]?\]", selector)
    return match.group(1) if match else None


def _target(step: dict[str, Any], attribute: str, for_input: bool) -> ElementInfo:
    candidates: list[Locator] = []
    name = None
    for alternative in step.get("selectors", []):
        chain = [alternative] if isinstance(alternative, str) else list(alternative)
        if len(chain) != 1 or not isinstance(chain[0], str):
            continue  # frames and shadow-DOM chains are not supported yet
        selector = chain[0]
        locator: Locator | None = None
        if selector.startswith("aria/"):
            match = _ARIA.match(selector)
            if match:
                name = match.group("name")
                role = match.group("role")
                if role:
                    locator = Locator(role=role, name=name)
                elif for_input:
                    locator = Locator(label=name)
                else:
                    locator = Locator(text=name)
        elif selector.startswith("text/"):
            locator = Locator(text=selector.removeprefix("text/"))
        elif selector.startswith("xpath/"):
            continue
        else:
            css = selector.removeprefix("pierce/")
            testid = _testid_css(css, attribute)
            locator = Locator(testid=testid) if testid else Locator(css=css)
        if locator is not None and locator not in candidates:
            candidates.append(locator)
    if not candidates:
        raise DevToolsImportError(f"step '{step.get('type')}' has no usable selector")
    return ElementInfo(tag="unknown", name=name, candidates=candidates)


def convert(flow: dict[str, Any], *, process: str | None = None, recording_id: str) -> list[Any]:
    """User flow JSON -> trace records (header, events, end)."""
    steps = flow.get("steps")
    if not isinstance(steps, list):
        raise DevToolsImportError("not a DevTools Recorder export: 'steps' is missing")
    attribute = str(flow.get("selectorAttribute") or "data-testid")
    start_url = next((s["url"] for s in steps if s.get("type") == "navigate"), None)
    if start_url is None:
        raise DevToolsImportError("the recording has no navigate step")
    header = TraceHeader(
        recording_id=recording_id,
        process=process,
        note=flow.get("title"),
        source="chrome-devtools-recorder",
        started_at=datetime.now(UTC),
        start_url=start_url,
    )
    events: list[TraceEvent] = []

    def add(kind: str, **fields: Any) -> None:
        events.append(TraceEvent(seq=len(events) + 1, t=float(len(events)), type=kind, **fields))

    for step in steps:
        kind = step.get("type")
        if kind == "setViewport":
            header.viewport = (int(step["width"]), int(step["height"]))
        elif kind == "navigate":
            add("navigate", value=step["url"], url=step["url"])
        elif kind in ("click", "doubleClick"):
            add("click", target=_target(step, attribute, for_input=False))
        elif kind == "change":
            add("fill", target=_target(step, attribute, for_input=True), value=str(step["value"]))
        elif kind == "keyDown":
            add("press", value=str(step["key"]))
        elif kind not in _SKIPPED:
            raise DevToolsImportError(f"unknown step type '{kind}'")
        for asserted in step.get("assertedEvents") or []:
            if asserted.get("type") == "navigation" and asserted.get("url"):
                add("navigated", url=asserted["url"], title=asserted.get("title"))
    end = TraceEnd(
        t=float(len(events)), ended_at=datetime.now(UTC), reason="imported",
        events=len(events), states=0,
    )  # fmt: skip
    return [header, *events, end]


def import_devtools_file(source: Path, out_dir: Path, *, process: str | None = None) -> Path:
    try:
        flow = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DevToolsImportError(f"{source}: not valid JSON ({exc})") from exc
    records = convert(flow, process=process, recording_id=out_dir.name)
    path = out_dir / "trace.jsonl"
    with TraceWriter(path) as writer:
        for record in records:
            writer.write(record)
    return path
