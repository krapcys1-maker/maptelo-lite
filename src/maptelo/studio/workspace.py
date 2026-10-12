"""The folder Studio works in: the same layout the command line uses.

    recordings/<process>/<id>/    a demonstration (trace.jsonl, screens/, data/)
    maps/<process>/model.yaml     a process model (with its report, SOP, questions, repairs)
    runs/<process>/<time>/        one run: results.jsonl, summary.json, evidence/, results sheet
    sheets/                       sheets people choose in Studio (copies, the originals stay)
    shadow/<process>/<check>/     a shadow check of one sheet (see studio/shadow.py)

A process is known by its folder name under maps/, so two versions of one model (before
and after an upgrade) are two processes with their own runs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from maptelo.mapping.naming import slug
from maptelo.model import ModelLoadError, load_model
from maptelo.model.schema import ProcessModel

SHEET_SUFFIXES = (".xlsx", ".xlsm", ".csv", ".tsv", ".txt")
_UNSAFE = re.compile(r"[^\w.\- ]+", re.UNICODE)
KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
"""A process's folder name: small letters, digits, - and _ (it is a file name everywhere)."""


def process_key(name: str) -> str:
    """The folder name of a process named in words: „Zmiana cen klientów” is
    zmiana-cen-klientow (a person names a process, they do not make up folder names)."""
    text = name.strip()
    if KEY.fullmatch(text):
        return text
    if not any(ch.isalnum() for ch in text):
        return ""  # no word to name a folder after („!!!”)
    return slug(text, 64).replace("_", "-")


@dataclass
class Process:
    key: str
    path: Path
    model: ProcessModel | None
    problems: list[str] = field(default_factory=list)

    @property
    def folder(self) -> Path:
        return self.path.parent

    def open_questions(self) -> int:
        """Questions still without an answer (a file that cannot be read counts as none:
        building the model again says what is wrong with it)."""
        questions = self.folder / "questions.yaml"
        if not questions.is_file():
            return 0
        try:
            data = YAML(typ="safe").load(questions.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError, YAMLError):
            return 0
        items = data.get("questions") if isinstance(data, dict) else None
        return sum(
            1 for item in items or [] if isinstance(item, dict) and item.get("answer") in (None, "")
        )

    def pending_repairs(self) -> int:
        """Repairs proposed after screens changed and not accepted yet: the repairs file next
        to the model (``<model>.repairs.yaml``, as the full Maptelo writes it)."""
        path = self.path.with_name(f"{self.path.stem}.repairs.yaml")
        if not path.is_file():
            return 0
        try:
            data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError, YAMLError):
            return 0
        items = data.get("repairs") if isinstance(data, dict) else None
        whole = ("kind", "old", "new")
        return sum(
            1 for item in items or [] if isinstance(item, dict) and all(k in item for k in whole)
        )


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    @property
    def maps(self) -> Path:
        return self.root / "maps"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def sheets(self) -> Path:
        return self.root / "sheets"

    @property
    def recordings(self) -> Path:
        return self.root / "recordings"

    def recording_folders(self, key: str) -> list[Path]:
        """Demonstrations of a process (recordings/<process>/<id>/trace.jsonl), oldest first."""
        if not KEY.fullmatch(key):
            return []
        folder = self.recordings / key
        if not folder.is_dir():
            return []
        return sorted(rec for rec in folder.iterdir() if (rec / "trace.jsonl").is_file())

    def drafts(self) -> list[str]:
        """Processes that have demonstrations but no model yet."""
        if not self.recordings.is_dir():
            return []
        return [
            folder.name
            for folder in sorted(self.recordings.iterdir())
            if KEY.fullmatch(folder.name)
            and self.recording_folders(folder.name)
            and not (self.maps / folder.name / "model.yaml").is_file()
        ]

    def processes(self) -> list[Process]:
        if not self.maps.is_dir():
            return []
        return [
            self._load(path.parent.name, path) for path in sorted(self.maps.glob("*/model.yaml"))
        ]

    def process(self, key: str) -> Process:
        path = self.maps / key / "model.yaml"
        if "/" in key or "\\" in key or key.startswith(".") or not path.is_file():
            raise KeyError(key)
        return self._load(key, path)

    @staticmethod
    def _load(key: str, path: Path) -> Process:
        try:
            return Process(key, path, load_model(path))
        except ModelLoadError as exc:
            return Process(key, path, None, list(exc.problems))

    def run_folders(self, key: str) -> list[Path]:
        """Runs of a process, the newest first."""
        folder = self.runs / key
        if not folder.is_dir():
            return []
        runs = [run for run in folder.iterdir() if (run / "batch.json").is_file()]
        return sorted(runs, key=lambda run: (run / "batch.json").stat().st_mtime, reverse=True)

    def new_run_folder(self, key: str) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return self.runs / key / stamp

    def keep_sheet(self, name: str, content: bytes) -> Path:
        """A copy of a sheet a person chose; the original file stays where it was."""
        last = Path(name.replace("\\", "/").rsplit("/", 1)[-1])  # a name, never a path
        stem, suffix = last.stem, last.suffix.lower()
        if suffix not in SHEET_SUFFIXES:
            raise ValueError(f"a sheet must be one of: {', '.join(SHEET_SUFFIXES)}")
        safe = _UNSAFE.sub("_", stem).strip(" .") or "arkusz"
        self.sheets.mkdir(parents=True, exist_ok=True)
        from uuid import uuid4

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + "-" + uuid4().hex[:12]
        path = self.sheets / f"{stamp}-{safe}{suffix}"
        with path.open("xb") as kept:
            kept.write(content)
        try:
            from maptelo.data.tables import read_table

            read_table(path)
        except Exception:
            path.unlink()
            raise
        return path

    def inside(self, path: str | Path) -> Path:
        """A path in the workspace (given relative to it, or absolute); nothing outside."""
        candidate = Path(path)
        full = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if not full.is_relative_to(self.root):
            raise PermissionError(f"{path} is outside the workspace")
        return full

    def relative(self, path: str | Path) -> str:
        return self.inside(path).relative_to(self.root).as_posix()


def read_run(folder: Path) -> dict[str, Any]:
    """What a run folder says: its summary and every record's latest result."""
    summary_file = folder / "summary.json"
    summary = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file.is_file() else {}
    latest: dict[int, dict[str, Any]] = {}
    results = folder / "results.jsonl"
    if results.is_file():
        for line in results.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # a line cut short by a crash
            latest[int(entry["record"])] = entry
    sheets = sorted(folder.glob("*.results.*"))
    when = datetime.fromtimestamp((folder / "batch.json").stat().st_mtime, UTC)
    return {
        "time": when.isoformat(timespec="seconds"),
        "summary": summary,
        "records": [latest[number] for number in sorted(latest)],
        "results_file": sheets[0] if sheets else None,
    }
