"""Recording a demonstration in Studio (a browser, or a Java program on this computer) and
the map of one demonstration: its steps as the person did them, the SOP, the BPMN diagram and
the report. What Maptelo Lite is; the full Maptelo builds a model of several demonstrations on
top of it.

Each does what the command line does (``record``, ``map``) over the same folders.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maptelo.browser import profile_dir
from maptelo.capture import RecorderOptions, new_recording_id, record_session
from maptelo.export import write_map_bundle
from maptelo.export.describe import choice_text
from maptelo.mapping import map_trace
from maptelo.mapping.naming import Lang
from maptelo.model import load_model
from maptelo.studio.common import BROWSERS, RunProblemError
from maptelo.studio.discard import discard
from maptelo.studio.jobs import Job
from maptelo.studio.polish import polish
from maptelo.studio.window import bring_forward, browser_windows, out_of_the_way
from maptelo.studio.workspace import KEY, SHEET_SUFFIXES, Workspace, process_key
from maptelo.trace import TraceError, load_trace, summarize
from maptelo.trace.schema import ACTION_TYPES


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
    lang: str = "pl"
    """The language of the words the page shows for the steps as they are recorded."""

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
            lang="en" if text("lang") == "en" else "pl",
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
        job.folder = folder
        feed = StepFeed(folder / "trace.jsonl", request.lang)
        job.emit("start", folder=workspace.relative(folder), url=request.url)
        options = RecorderOptions(
            process=request.process,
            title=request.title,
            note=request.note,
            data=sheet,
            sheet=request.sheet_name,
            private=request.private,
        )
        before = set(browser_windows())  # Studio's own window, the person's browsers

        def in_front() -> None:  # over a program the person had open (SRK), not behind it
            opened = [window for window in browser_windows() if window not in before]
            if opened:
                bring_forward(opened[0])

        with out_of_the_way():  # the demonstration's window in front, Studio back after
            path = record_session(
                request.url,
                folder,
                options,
                channel=BROWSERS[request.browser],
                profile=profile_dir(request.profile) if request.profile else None,
                storage_state=session,
                stop=lambda: job.stop_requested,
                progress=lambda events: feed.tell(job, events),
                on_open=in_front,
                listen=lambda ear: setattr(job, "hear", ear),
            )
        feed.tell(job)  # what it wrote as it ended
        return _recorded(workspace, request, folder, path)

    return work


STEP_WORDS: dict[str, dict[str, str]] = {
    "pl": {
        "click": "Kliknięcie {name}",
        "fill": "Wpisanie w {name}",
        "select": "Wybór w {name}",
        "check": "Zaznaczenie {name}",
        "uncheck": "Odznaczenie {name}",
        "press": "Klawisz {value}",
        "navigate": "Otwarcie strony {value}",
        "upload": "Załączenie pliku w {name}",
        "window": "okno {window}",
        "element": "elementu",
    },
    "en": {
        "click": "Click on {name}",
        "fill": "Typing into {name}",
        "select": "Choice in {name}",
        "check": "Ticking {name}",
        "uncheck": "Unticking {name}",
        "press": "Key {value}",
        "navigate": "Opening the page {value}",
        "upload": "File attached in {name}",
        "window": "window {window}",
        "element": "an element",
    },
}
"""A recorded action in a few words, as Studio's list of steps shows it while recording."""


def step_words(event: Mapping[str, Any], lang: str) -> str:
    """„Kliknięcie „Przeglądaj…” · okno „Import cennika”” for an action of a trace: what was
    done, on what, where (a field's value only when it is no secret, shortened)."""
    w = STEP_WORDS["en" if lang == "en" else "pl"]
    open_, close = ("“", "”") if lang == "en" else ("„", "”")
    target = event.get("target") or {}
    named = next(
        (
            str(target[k]).strip()
            for k in ("name", "label", "text", "column")
            if isinstance(target.get(k), str) and str(target[k]).strip()
        ),
        "",
    )
    name = f"{open_}{named[:60]}{close}" if named else w["element"]
    value = str(event.get("value") or "")
    words = w.get(str(event.get("type")), w["click"]).format(name=name, value=value[:80])
    if event.get("type") in ("fill", "select") and value and not event.get("secret"):
        words += f": {value[:40]}"
    url = str(event.get("url") or "")
    window = url.rsplit("/", 1)[-1] if url.startswith("java://") else str(event.get("title") or "")
    if window.strip():
        words += " · " + w["window"].format(window=f"{open_}{window.strip()[:60]}{close}")
    return words


class StepFeed:
    """The actions of a recording as it runs, read from its trace file as the recorder writes
    them: each told once to the page, with its number, to be described there one by one (the
    person saw only how many events there were, and what they said went to the last step)."""

    def __init__(self, path: Path, lang: str) -> None:
        self.path = path
        self.lang = lang
        self.offset = 0

    def new(self) -> list[dict[str, Any]]:
        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read()
        except OSError:
            return []
        end = chunk.rfind(b"\n")
        if end < 0:
            return []  # a line still being written: next time
        self.offset += end + 1
        steps = []
        for line in chunk[: end + 1].decode("utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if not isinstance(item, dict) or item.get("kind") != "event":
                continue
            if item.get("type") not in ACTION_TYPES or not isinstance(item.get("seq"), int):
                continue
            steps.append({"action": item["seq"], "words": step_words(item, self.lang)})
        return steps

    def tell(self, job: Job, events: int | None = None) -> None:
        """The job hears how many events there are, then the new steps (``events`` None: only
        the steps, the last ones a recording wrote as it ended)."""
        if events is not None:
            job.emit("progress", events=events)
        for step in self.new():
            job.emit("step", **step)


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


def java_programs(lang: Lang = "pl") -> dict[str, Any]:
    """The Java programs open on this desktop (their main windows' titles, front first), to
    record one; and whether this computer has the bridge library that sees them."""
    if not ON_WINDOWS:
        problem = JAVA_ON_WINDOWS if lang == "en" else polish(JAVA_ON_WINDOWS)
        return {"windows": [], "bridge": False, "problem": problem}
    from maptelo.desktop import jab

    windows = jab.java_frames()
    own = [jab.program_folder(w.pid) for w in windows]
    library = jab.bridge_library([folder for folder in own if folder is not None])
    trouble: str | None = None
    if library is not None and not library.usable:  # a 32-bit Java, and no 32-bit Python
        said = jab.no_helper(library)
        trouble = said if lang == "en" else polish(said)
    return {
        "windows": [{"title": w.title} for w in windows],
        "bridge": library is not None and library.usable,
        "problem": trouble,
    }


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
        job.folder = folder
        feed = StepFeed(folder / "trace.jsonl", request.lang)
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
        job.hear = recorder.note
        job.emit("start", folder=workspace.relative(folder), program=main.title)
        with out_of_the_way():  # the program in front, Studio back when the recording ends
            bring_forward(main.hwnd)
            path = recorder.record_until(
                stop=lambda: job.stop_requested,
                progress=lambda events: feed.tell(job, events),
            )
        feed.tell(job)  # what it wrote as it ended
        return _recorded(workspace, request, folder, path)

    return work


MAP_FILES = (
    "report.html",
    "process.svg",
    "sop.md",
    "process.bpmn",
    "process.mmd",
    "model.yaml",
    "ai-brief.md",
    "ai-brief.json",
)
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
                "title": header.title,
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


def process_title(workspace: Workspace, key: str) -> str | None:
    """The process's name as the person typed it („Customer price change”), from its newest
    recording that has one: only the first line of each is read."""
    for folder in reversed(workspace.recording_folders(key)):
        try:
            with (folder / "trace.jsonl").open(encoding="utf-8") as file:
                header = json.loads(file.readline())
        except (OSError, ValueError):
            continue
        title = header.get("title") if isinstance(header, dict) else None
        if isinstance(title, str) and title.strip():
            return title.strip()
    return None


def forget_process(workspace: Workspace, key: str) -> list[str]:
    """A process the person no longer wants, deleted whole: its recordings and maps (and in
    the full Maptelo its runs and shadow checks). On Windows into the Recycle Bin."""
    folders = [workspace.recordings, workspace.maps, workspace.runs, workspace.root / "shadow"]
    present = [base / key for base in folders if KEY.fullmatch(key) and (base / key).exists()]
    if not present:
        raise RunProblemError([f"there is no process {key!r}"])
    discard(present)
    return [workspace.relative(folder) for folder in present]


def forget_recording(workspace: Workspace, key: str, recording: str) -> list[str]:
    """One demonstration deleted, with its own map (Maptelo Lite's); a process left without
    recordings is deleted with it, as no list shows it any more."""
    folders = {folder.name: folder for folder in workspace.recording_folders(key)}
    folder = folders.get(recording)
    if folder is None:
        raise RunProblemError([f"there is no recording {recording!r} of {key!r}"])
    own_map = workspace.maps / key / recording
    present = [folder, *([own_map] if own_map.is_dir() else [])]
    discard(present)
    removed = [workspace.relative(path) for path in present]
    if not workspace.recording_folders(key) and not (workspace.maps / key / "model.yaml").exists():
        removed += forget_process(workspace, key)
    return removed


CARD = "card.json"
"""What the process is for, in the person's words (the process card: goal, data, scope, done,
failures, never), next to its recordings; every map of the process starts with it."""


def process_card(workspace: Workspace, key: str) -> dict[str, str]:
    """The process card as the person wrote it (only what was answered)."""
    from maptelo.model.schema import CARD_FIELDS

    if not KEY.fullmatch(key):
        return {}
    try:
        kept = json.loads((workspace.recordings / key / CARD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(kept, dict):
        return {}
    return {
        k: v.strip()
        for k, v in kept.items()
        if k in CARD_FIELDS and isinstance(v, str) and v.strip()
    }


def write_process_card(
    workspace: Workspace, key: str, answers: dict[str, Any], lang: str = "pl"
) -> dict[str, str]:
    """The card written (an empty answer removes one), and every map of the process made again
    with it."""
    from maptelo.model.schema import CARD_FIELDS

    folders = workspace.recording_folders(key)
    if not folders:
        raise RunProblemError([f"there is no process {key!r}"])
    card = {k: str(answers.get(k) or "").strip() for k in CARD_FIELDS}
    card = {k: v for k, v in card.items() if v}
    (workspace.recordings / key / CARD).write_text(
        json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for folder in folders:
        if map_files(workspace, key, folder.name) is not None:
            map_recording(workspace, key, folder.name, lang)
    return card


NOTES = "notes.json"
"""Descriptions of steps written on a recording's map afterwards, by the step's first action
(the recording's own folder: a map made again keeps them)."""


def written_notes(folder: Path) -> dict[int, str | dict[str, Any]]:
    """By an action's number: why (plain words), or why, when, whether a person decides."""
    try:
        kept = json.loads((folder / NOTES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(kept, dict):
        return {}
    return {int(k): v for k, v in kept.items() if str(k).isdigit() and isinstance(v, str | dict)}


def keep_note(folder: Path, seq: int, text: str, when: str = "", person: bool = False) -> None:
    """A step's description kept with its recording, by an action of the step (an empty one
    takes back what was said)."""
    kept = written_notes(folder)
    said: str | dict[str, Any] = text.strip()
    if when.strip() or person:
        said = {"text": text.strip(), "when": when.strip(), "person": bool(person)}
    kept[seq] = said
    folder.mkdir(parents=True, exist_ok=True)
    (folder / NOTES).write_text(
        json.dumps({str(k): v for k, v in sorted(kept.items())}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def write_note(
    workspace: Workspace,
    key: str,
    recording: str,
    first: int,
    text: str,
    when: str = "",
    person: bool = False,
) -> None:
    """A step's description written on the map (an empty one removes what was said)."""
    folder = {f.name: f for f in workspace.recording_folders(key)}.get(recording)
    if folder is None:
        raise RunProblemError([f"there is no recording {recording!r} of {key!r}"])
    keep_note(folder, first, text, when, person)


def map_steps_view(
    workspace: Workspace, key: str, recording: str, lang: Lang = "pl"
) -> list[dict[str, Any]]:
    """A recording's map, step by step, with what describes each (to write it on the page)
    and, for a decision the recording made one way, what else was offered."""
    path = workspace.maps / key / recording / "model.yaml"
    if not path.is_file():
        raise RunProblemError([f"there is no map of the recording {recording!r} of {key!r}"])
    model = load_model(path)
    steps = []
    for number, step in enumerate(model.steps, start=1):
        seqs = [
            int(trace.rsplit("#", 1)[1])
            for trace in (step.evidence.traces if step.evidence else [])
            if trace.rsplit("#", 1)[-1].isdigit()
        ]
        steps.append(
            {
                "number": number,
                "intent": step.intent,
                "note": step.note,
                "when": step.note_when,
                "person": step.person_decides,
                "choice": choice_text(step, model, lang),
                "first": min(seqs, default=None),
            }
        )
    return steps


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
    result = map_trace(trace, lang=language, process_id=key, notes=written_notes(folder))
    card = process_card(workspace, key)
    if card:
        from maptelo.model.schema import ProcessCard

        result.model = result.model.model_copy(update={"card": ProcessCard.model_validate(card)})
    write_map_bundle(result, workspace.maps / key / recording, lang=language)
    return {
        "process": key,
        "recording": recording,
        "steps": len(result.model.steps),
        "notes": list(result.notes),
        "map": map_files(workspace, key, recording),
    }
