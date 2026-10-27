"""Screenshots for documents: the screen of each step with the element marked."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

from maptelo.mapping.build import MapResult
from maptelo.model.schema import Action, ProcessModel
from maptelo.trace.schema import Trace, TraceState

_MARK = (220, 38, 38)
_BADGE = (30, 41, 59)
"""The step's number next to the frame: dark, so that the frame stays the only red."""


def annotate(
    source: Path,
    bbox: tuple[int, int, int, int] | None,
    target: Path,
    max_width: int = 960,
    *,
    number: int | None = None,
) -> Path:
    """Copy a screenshot, draw a frame around the element (and the step's ``number`` by it, so
    a document can name the picture), scale it down for documents."""
    with Image.open(source) as opened:
        image = opened.convert("RGB")
    if bbox is not None:
        x, y, width, height = bbox
        draw = ImageDraw.Draw(image)
        for grow in range(4, 7):
            draw.rectangle([x - grow, y - grow, x + width + grow, y + height + grow], outline=_MARK)
        if number is not None:
            _badge(draw, image.size, (x - 7, y - 7), str(number))
    if image.width > max_width:
        image = image.resize((max_width, round(image.height * max_width / image.width)))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "JPEG", quality=82)
    return target


def _badge(
    draw: ImageDraw.ImageDraw, size: tuple[int, int], corner: tuple[int, int], text: str
) -> None:
    """The step's number in a dark box just above and left of the frame's corner (inside the
    picture when the element is at its edge)."""
    font = ImageFont.load_default(size=15)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    width, height = right - left + 10, bottom - top + 8
    x = min(max(0, corner[0] - width), max(0, size[0] - width))
    y = min(max(0, corner[1] - height), max(0, size[1] - height))
    draw.rectangle([x, y, x + width, y + height], fill=_BADGE)
    draw.text((x + 5 - left, y + 4 - top), text, fill=(255, 255, 255), font=font)


def _path(address: str) -> str:
    return urlparse(address).path.rstrip("/") or "/"


def _opened(trace: Trace, address: str, since: float) -> TraceState | None:
    """The screen a step opens by its address, as it showed. An application may first ask to
    sign in (the person does, then it opens what was asked: the clean-Windows Lite test of
    12.10 showed the sign-in under "Open the Customer prices screen"): the picture is of the
    screen the step opens."""
    wanted = _path(address)
    shown = sorted(trace.states.values(), key=lambda state: state.t)
    return next((s for s in shown if s.t >= since and _path(s.url) == wanted), None)


def screenshots_for(
    model: ProcessModel,
    sources: Mapping[str, tuple[Trace, Sequence[int]]],
    out_dir: Path,
) -> dict[str, str]:
    """Step id -> image path (relative to out_dir); ``sources`` says which recording and
    trace events each step comes from (steps of one model may come from several)."""
    images: dict[str, str] = {}
    for index, step in enumerate(model.steps, start=1):
        trace, seqs = sources.get(step.id, (None, ()))
        if trace is None or trace.path is None or not seqs:
            continue
        if model.private and not trace.header.private:
            continue  # a picture taken uncovered: a private process shows none of it
        event = next((e for e in trace.events if e.seq == seqs[-1]), None)
        if event is None:
            continue
        navigate = event.type == "navigate"
        state = trace.state(event.state_after if navigate else event.state_before)
        if step.action == Action.NAVIGATE and step.value:
            first = next((e for e in trace.events if e.seq == seqs[0]), event)
            state = _opened(trace, str(step.value), first.t) or state
            navigate = True  # a whole screen: no element to mark
        if state is None or state.screenshot is None:
            continue
        if state.screenshot_t is not None:
            continue  # taken later than the screen it stands for: a field may show its typing
        source = trace.path.parent / state.screenshot
        if not source.is_file():
            continue
        bbox = None if navigate or event.target is None else event.target.bbox
        if bbox is not None and state.origin is not None:  # the screen's place, on the picture
            x, y, width, height = bbox
            scale = state.scale or 1.0
            bbox = (
                round((x - state.origin[0]) * scale),
                round((y - state.origin[1]) * scale),
                round(width * scale),
                round(height * scale),
            )
        relative = f"images/step-{index:02d}.jpg"
        annotate(source, bbox, out_dir / relative, number=index)
        images[step.id] = relative
    return images


def step_screenshots(result: MapResult, out_dir: Path) -> dict[str, str]:
    """Step id -> image path (relative to out_dir) for steps whose screen was captured."""
    sources = {step_id: (result.trace, seqs) for step_id, seqs in result.step_events.items()}
    return screenshots_for(result.model, sources, out_dir)
