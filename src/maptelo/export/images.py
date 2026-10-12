"""Screenshots for documents: the screen of each step with the element marked."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from PIL import Image, ImageDraw

from maptelo.mapping.build import MapResult
from maptelo.model.schema import ProcessModel
from maptelo.trace.schema import Trace

_MARK = (220, 38, 38)


def annotate(
    source: Path, bbox: tuple[int, int, int, int] | None, target: Path, max_width: int = 960
) -> Path:
    """Copy a screenshot, draw a frame around the element, scale it down for documents."""
    with Image.open(source) as opened:
        image = opened.convert("RGB")
    if bbox is not None:
        x, y, width, height = bbox
        draw = ImageDraw.Draw(image)
        for grow in range(4, 7):
            draw.rectangle([x - grow, y - grow, x + width + grow, y + height + grow], outline=_MARK)
    if image.width > max_width:
        image = image.resize((max_width, round(image.height * max_width / image.width)))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "JPEG", quality=82)
    return target


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
        event = next((e for e in trace.events if e.seq == seqs[-1]), None)
        if event is None:
            continue
        navigate = event.type == "navigate"
        state = trace.state(event.state_after if navigate else event.state_before)
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
            bbox = (x - state.origin[0], y - state.origin[1], width, height)
        relative = f"images/step-{index:02d}.jpg"
        annotate(source, bbox, out_dir / relative)
        images[step.id] = relative
    return images


def step_screenshots(result: MapResult, out_dir: Path) -> dict[str, str]:
    """Step id -> image path (relative to out_dir) for steps whose screen was captured."""
    sources = {step_id: (result.trace, seqs) for step_id, seqs in result.step_events.items()}
    return screenshots_for(result.model, sources, out_dir)
