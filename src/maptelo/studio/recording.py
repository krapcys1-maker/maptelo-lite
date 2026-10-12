"""Recording a demonstration in Studio (a browser, or a Java program on this computer) and
the map of one demonstration: its steps as the person did them, the SOP, the BPMN diagram and
the report. What Maptelo Lite is; the full Maptelo builds a model of several demonstrations on
top of it.

Each does what the command line does (``record``, ``map``) over the same folders.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maptelo.browser import profile_dir
from maptelo.capture import RecorderOptions, new_recording_id, record_session
from maptelo.export import write_map_bundle
from maptelo.mapping import map_trace
from maptelo.mapping.naming import Lang
from maptelo.studio.common import BROWSERS, RunProblemError
from maptelo.studio.jobs import Job
from maptelo.studio.polish import polish
from maptelo.studio.window import bring_forward, out_of_the_way
from maptelo.studio.workspace import KEY, SHEET_SUFFIXES, Workspace, process_key
from maptelo.trace import TraceError, load_trace, summarize


@dataclass(frozen=True)
class RecordRequest:
    process: str
    url: str
    title: str | None = None
    """The name as the person typed it, when it is not the folder name itself."""
    note: str | None = None
    sheet: str | None = None
    """A sheet in the workspace the person takes values from (its copy goes with the recording)."""
    sheet_name: str | None = None
    private: bool = False
    browser: str = "chromium"
    profile: str | None = None
    session: str | None = None
    java: str | None = None
    """A part of a Java program's main window title: the demonstration is done in that
    program (seen through the Java Access Bridge), not in a browser."""

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> RecordRequest:
        def text(name: str) -> str | None:
            value = data.get(name)
            if value is None or (isinstance(value, str) and not value.strip()):
                return None
            if not isinstance(value, str):
                raise RunProblemError([f"'{name}' must be text"])
            return value.strip()

        named = text("process") or ""
        key = process_key(named) if named else ""
        return cls(
            process=key,
            url=text("url") or "",
            title=named if named != key else None,
            note=text("note"),
            sheet=text("sheet"),
            sheet_name=text("sheet_name"),
            private=bool(data.get("private", False)),
            browser=text("browser") or "chromium",
            profile=text("profile"),
            session=text("session"),
            java=text("java"),
        )


def check_record(workspace: Workspace, request: RecordRequest) -> tuple[Path | None, Path | None]:
    """Problems before a browser opens; the sheet and the session file if all is well."""
    problems = []
    if not KEY.fullmatch(request.process):
        problems.append("the process needs a name with letters or digits, e.g. Ceny klientów")
    if request.java:
        if not ON_WINDOWS:
            problems.append(JAVA_ON_WINDOWS)
    else:
        if not request.url.startswith(("http://", "https://")):
            problems.append("the address must start with http:// or https://")
        if request.browser not in BROWSERS:
            problems.append(f"the browser must be one of: {', '.join(BROWSERS)}")
        if request.profile and request.session:
            problems.append("a profile keeps the sign-in itself: choose a profile or a session")
    session = None
    if request.session and not request.java:
        session = Path(request.session).expanduser()
        if not session.is_file():
            problems.append(f"there is no session file {request.session}")
    sheet = None
    if request.sheet:
        try:
            sheet = workspace.inside(request.sheet)
        except PermissionError as exc:
            problems.append(str(exc))
        else:
            if not sheet.is_file() or sheet.suffix.lower() not in SHEET_SUFFIXES:
                problems.append(f"there is no sheet {request.sheet}")
    if problems:
        raise RunProblemError(problems)
    return sheet, session


def record_work(workspace: Workspace, request: RecordRequest) -> Callable[[Job], dict[str, Any]]:
    sheet, session = check_record(workspace, request)
    if request.java:
        return _java_work(workspace, request, sheet)

    def work(job: Job) -> dict[str, Any]:
        folder = workspace.recordings / request.process / new_recording_id()
        job.emit("start", folder=workspace.relative(folder), url=request.url)
        options = RecorderOptions(
            process=request.process,
            title=request.title,
            note=request.note,
            data=sheet,
            sheet=request.sheet_name,
            private=request.private,
        )
        with out_of_the_way():  # the demonstration's window in front, Studio back after
            path = record_session(
                request.url,
                folder,
                options,
                channel=BROWSERS[request.browser],
                profile=profile_dir(request.profile) if request.profile else None,
                storage_state=session,
                stop=lambda: job.stop_requested,
                progress=lambda events: job.emit("progress", events=events),
            )
        return _recorded(workspace, request, folder, path)

    return work


def _recorded(
    workspace: Workspace, request: RecordRequest, folder: Path, path: Path
) -> dict[str, Any]:
    trace = load_trace(path)
    return {
        "process": request.process,
        "folder": workspace.relative(folder),
        "recording": folder.name,
        "actions": len(trace.actions()),
        "summary": summarize(trace),
    }


ON_WINDOWS = sys.platform == "win32"
"""Java programs are recorded on Windows only (a test says otherwise here, never for the
whole of Python: what else asks which system this is must hear the truth)."""
JAVA_ON_WINDOWS = "a Java program can be recorded on Windows only"


def java_programs() -> dict[str, Any]:
    """The Java programs open on this desktop (their main windows' titles, front first), to
    record one; and whether this computer has the bridge library that sees them."""
    if not ON_WINDOWS:
        return {"windows": [], "bridge": False, "problem": polish(JAVA_ON_WINDOWS)}
    from maptelo.desktop import jab

    windows = jab.java_frames()
    own = [jab.program_folder(w.pid) for w in windows]
    bridge = jab.find_dll([folder for folder in own if folder is not None]) is not None
    return {"windows": [{"title": w.title} for w in windows], "bridge": bridge, "problem": None}


def _java_work(
    workspace: Workspace, request: RecordRequest, sheet: Path | None
) -> Callable[[Job], dict[str, Any]]:
    """A demonstration in a Java program: the person works in the program, Studio waits on
    the taskbar until they come back and say it is done (or close the program)."""
    from maptelo.capture import java
    from maptelo.desktop import jab

    wanted = request.java or ""

    def work(job: Job) -> dict[str, Any]:
        folder = workspace.recordings / request.process / new_recording_id()
        mine = [w for w in jab.java_frames() if wanted.casefold() in w.title.casefold()]
        own = [jab.program_folder(w.pid) for w in mine]
        options = java.JavaRecorderOptions(
            window=wanted,
            process=request.process,
            title=request.title,
            note=request.note,
            data=sheet,
            sheet=request.sheet_name,
            private=request.private,
            java_dirs=tuple(f for f in own if f is not None),
            raw_events=bool(os.environ.get("MAPTELO_JAVA_EVENTS")),  # as the command line
        )
        recorder = java.JavaRecorder(folder, options)
        try:
            main = recorder.start(timeout=10)
        except jab.AccessBridgeError:
            raise  # what the bridge says, in its own sentence
        except RuntimeError as exc:
            raise RunProblemError(
                [
                    f"the Java program “{wanted}” is not open, or the Java Access Bridge is off "
                    "for it: IT turns it on with jabswitch -enable, then the program is started "
                    "again"
                ]
            ) from exc
        job.emit("start", folder=workspace.relative(folder), program=main.title)
        with out_of_the_way():  # the program in front, Studio back when the recording ends
            bring_forward(main.hwnd)
            path = recorder.record_until(
                stop=lambda: job.stop_requested,
                progress=lambda events: job.emit("progress", events=events),
            )
        return _recorded(workspace, request, folder, path)

    return work


MAP_FILES = ("report.html", "process.svg", "sop.md", "process.bpmn", "process.mmd", "model.yaml")
"""What the map of one demonstration is (export.write_map_bundle), in the order it is shown."""


def recordings_view(workspace: Workspace, key: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for folder in workspace.recording_folders(key):
        try:
            trace = load_trace(folder)
        except (TraceError, OSError, ValueError) as exc:
            found.append({"id": folder.name, "problem": str(exc)})
            continue
        header = trace.header
        found.append(
            {
                "id": folder.name,
                "note": header.note,
                "started": header.started_at.isoformat(timespec="seconds"),
                "url": header.start_url,
                "program": header.program,
                "actions": len(trace.actions()),
                "data": header.data.file if header.data else None,
                "private": header.private,
                "ended": trace.end.reason if trace.end else None,
                "map": map_files(workspace, key, folder.name),
            }
        )
    return found


def map_files(workspace: Workspace, key: str, recording: str) -> dict[str, str] | None:
    """The files of a demonstration's own map (None: not mapped yet), as workspace paths."""
    folder = workspace.maps / key / recording
    if not (folder / "report.html").is_file():
        return None
    return {
        name: workspace.relative(folder / name) for name in MAP_FILES if (folder / name).is_file()
    }


def map_recording(
    workspace: Workspace, key: str, recording: str, lang: str = "pl"
) -> dict[str, Any]:
    """One demonstration's map (Maptelo Lite: no model of several demonstrations, no robot):
    its steps as the person did them, the SOP, the BPMN diagram and the report, into
    maps/<process>/<recording>/. Made again over the old one."""
    folders = {folder.name: folder for folder in workspace.recording_folders(key)}
    folder = folders.get(recording)
    if folder is None:
        raise RunProblemError([f"there is no recording {recording!r} of {key!r}"])
    try:
        trace = load_trace(folder)
    except (TraceError, OSError, ValueError) as exc:
        raise RunProblemError([str(exc)]) from exc
    language: Lang = "en" if lang == "en" else "pl"
    result = map_trace(trace, lang=language, process_id=key)
    write_map_bundle(result, workspace.maps / key / recording, lang=language)
    return {
        "process": key,
        "recording": recording,
        "steps": len(result.model.steps),
        "notes": list(result.notes),
        "map": map_files(workspace, key, recording),
    }
