"""Writing traces line by line and loading them back with validation."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import IO

from pydantic import BaseModel, TypeAdapter, ValidationError

from maptelo.trace.schema import (
    Trace,
    TraceEnd,
    TraceEvent,
    TraceHeader,
    TraceRecord,
    TraceState,
)

_RECORD: TypeAdapter[TraceRecord] = TypeAdapter(TraceRecord)


class TraceError(Exception):
    """A trace file is malformed or inconsistent."""


class TraceWriter:
    """Appends records and flushes each one, so a crash loses at most the current line."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file: IO[str] = path.open("w", encoding="utf-8", newline="\n")

    def write(self, record: BaseModel) -> None:
        self._file.write(record.model_dump_json(exclude_none=True) + "\n")
        self._file.flush()

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def __enter__(self) -> TraceWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def load_trace(path: Path | str) -> Trace:
    """Read a trace (a trace.jsonl file or the folder containing one) and check it."""
    path = Path(path)
    file = path / "trace.jsonl" if path.is_dir() else path
    trace: Trace | None = None
    for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = _RECORD.validate_json(line)
        except ValidationError as exc:
            raise TraceError(f"{file}:{number}: {exc.errors()[0]['msg']}") from exc
        if trace is None:
            if not isinstance(record, TraceHeader):
                raise TraceError(f"{file}:{number}: the first record must be the header")
            trace = Trace(header=record, path=file)
            continue
        if trace.end is not None:
            raise TraceError(f"{file}:{number}: records after the end record")
        if isinstance(record, TraceHeader):
            raise TraceError(f"{file}:{number}: a second header")
        if isinstance(record, TraceEvent):
            if trace.events and record.seq <= trace.events[-1].seq:
                raise TraceError(f"{file}:{number}: event numbers must increase")
            trace.events.append(record)
        elif isinstance(record, TraceState):
            if record.id in trace.states:
                raise TraceError(f"{file}:{number}: state '{record.id}' appears twice")
            trace.states[record.id] = record
        elif isinstance(record, TraceEnd):
            trace.end = record
    if trace is None:
        raise TraceError(f"{file}: empty trace")
    for event in trace.events:
        for ref in (event.state_before, event.state_after):
            if ref is not None and ref not in trace.states:
                raise TraceError(f"{file}: event {event.seq} refers to unknown state '{ref}'")
    return trace
