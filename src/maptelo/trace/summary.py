"""A readable listing of a recording, for people checking what was captured."""

from __future__ import annotations

from urllib.parse import urlsplit

from maptelo.trace.schema import Trace, TraceEvent


def _path(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def describe_event(event: TraceEvent) -> str:
    target = event.target.describe() if event.target else ""
    match event.type:
        case "navigate":
            text = f"open {_path(event.value)}"
        case "navigated":
            text = f"-> {_path(event.url)}"
        case "fill":
            shown = "*** (secret)" if event.secret else f'"{event.value}"'
            text = f"fill {target} = {shown}"
        case "select":
            label = f" ({event.option_label})" if event.option_label else ""
            text = f'select {target} = "{event.value}"{label}'
        case "press":
            text = f"press {event.value}" + (f" in {target}" if target else "")
        case "appeared":
            element = event.target
            role = (element.role if element else None) or "element"
            name = f' "{element.name}"' if element and element.name else ""
            body = element.text if element and element.text else ""
            text = f"appeared {role}{name}" + (f": {body[:80]}" if body else "")
        case _:
            text = f"{event.type} {target}"
    if event.target and event.target.row and event.type != "appeared":
        cells = ", ".join(f"{k}={v}" for k, v in event.target.row.cells.items() if v and k)
        text += f"  [row: {cells}]"
    if event.target and event.target.dialog and event.type != "appeared":
        text += f"  [in dialog {event.target.dialog!r}]"
    return text


def summarize(trace: Trace) -> str:
    header = trace.header
    lines = [
        f"{header.recording_id}  {header.process or '(no process)'}  {header.source}",
        f"started {header.started_at.isoformat()} at {header.start_url}",
    ]
    if header.note:
        lines.append(f"note: {header.note}")
    for event in trace.events:
        marker = " " if event.is_action else "."
        lines.append(f"{marker}{event.seq:>4} {event.t:7.1f}s  {describe_event(event)}")
    actions = len(trace.actions())
    lines.append(
        f"{actions} actions, {len(trace.events) - actions} observations, {len(trace.states)} states"
    )
    return "\n".join(lines)
