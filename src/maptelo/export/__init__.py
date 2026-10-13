"""Documents made from a process model: SOP, diagram, BPMN and an HTML report."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from pathlib import Path

from maptelo.export.bpmn import render_bpmn
from maptelo.export.html import render_html
from maptelo.export.images import screenshots_for, step_screenshots
from maptelo.export.mermaid import render_mermaid
from maptelo.export.sop import render_sop
from maptelo.export.svg import render_svg
from maptelo.mapping.build import MapResult
from maptelo.mapping.naming import Lang, written_date
from maptelo.model import ProcessModel, dump_model, lint
from maptelo.trace.schema import Trace


def _inline(images: dict[str, str], out_dir: Path) -> dict[str, str]:
    """Images as data URIs, so the HTML report is one file that can be sent as it is."""
    encoded = {}
    for step_id, relative in images.items():
        data = base64.b64encode((out_dir / relative).read_bytes()).decode("ascii")
        encoded[step_id] = f"data:image/jpeg;base64,{data}"
    return encoded


def write_bundle(
    model: ProcessModel,
    out_dir: Path,
    *,
    lang: Lang = "pl",
    notes: Sequence[str] = (),
    sources: Mapping[str, tuple[Trace, Sequence[int]]] | None = None,
    source: str | None = None,
    several_sources: bool = False,
    header: str | None = None,
    warnings: bool = True,
) -> dict[str, Path]:
    """Write model.yaml, sop.md, process.mmd, process.svg, process.bpmn, report.html
    (+ images/). ``source`` names the recording(s) the model is made from (``several_sources``:
    more than one); ``warnings``: the model's lint findings in the report, for whoever edits
    the model (a single recording's map leaves them out: its report is for people doing the
    process, and the findings are the model file's English)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    images = screenshots_for(model, sources or {}, out_dir)
    yaml_text = dump_model(model, header=header)
    files = {
        "model": out_dir / "model.yaml",
        "sop": out_dir / "sop.md",
        "mermaid": out_dir / "process.mmd",
        "svg": out_dir / "process.svg",
        "bpmn": out_dir / "process.bpmn",
        "report": out_dir / "report.html",
    }
    contents = {
        "model": yaml_text,
        "sop": render_sop(
            model, lang=lang, notes=notes, images=images, source=source, sources=several_sources
        ),
        "mermaid": render_mermaid(model, lang=lang),
        "svg": render_svg(model, lang=lang),
        "bpmn": render_bpmn(model, lang=lang),
        "report": render_html(
            model,
            lang=lang,
            notes=notes,
            issues=lint(model) if warnings else (),
            images=_inline(images, out_dir),
            source=source,
            sources=several_sources,
            yaml_text=yaml_text,
        ),
    }
    for key, path in files.items():
        path.write_text(contents[key], encoding="utf-8", newline="\n")
    return files


def write_map_bundle(result: MapResult, out_dir: Path, *, lang: Lang = "pl") -> dict[str, Path]:
    """The map of one recording (M2)."""
    trace = result.trace
    recording = trace.header.recording_id
    return write_bundle(
        result.model,
        out_dir,
        lang=lang,
        notes=result.notes,
        sources={step_id: (trace, seqs) for step_id, seqs in result.step_events.items()},
        source=f"{written_date(trace.header.started_at.date(), lang)} ({recording})",
        header=(
            f"Maptelo process model, mapped from recording {recording}.\n"
            "Edit freely; check with: maptelo model validate <this file>"
        ),
        warnings=False,
    )


__all__ = [
    "render_bpmn",
    "render_html",
    "render_mermaid",
    "render_sop",
    "render_svg",
    "screenshots_for",
    "step_screenshots",
    "write_bundle",
    "write_map_bundle",
]
