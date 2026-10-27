"""Writing traces line by line and loading them back with validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import TracebackType
from typing import IO
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, TypeAdapter, ValidationError

from maptelo.formats import TRACE_VERSIONS, NewerFormatError, upgraded
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


_CREDENTIAL = re.compile(
    r"token|passw|pwd|secret|signature|jwt|api[-_]?key|session[-_]?id"
    r"|^sid$|^otp$|^auth(?:orization)?$",
    re.IGNORECASE,
)
"""Address parameters that sign in or prove who one is (?access_token=, &sessionid=)."""
HIDDEN = "hidden"


def hide_credentials(url: str) -> str:
    """The address without what signs in: a password in it (user:password@host) and the
    values of parameters like access_token or sessionid, in its query or after its #. The
    rest stays: a record's number in an address is what a model is made of."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.scheme.startswith("http"):
        return url
    netloc = parts.netloc
    if parts.password is not None:
        netloc = netloc.replace(f":{parts.password}@", f":{HIDDEN}@", 1)

    def clean(query: str) -> str:
        if "=" not in query:
            return query
        pairs = parse_qsl(query, keep_blank_values=True)
        if not any(_CREDENTIAL.search(name) for name, _ in pairs):
            return query
        return urlencode([(n, HIDDEN if _CREDENTIAL.search(n) else v) for n, v in pairs])

    cleaned = urlunsplit(
        (parts.scheme, netloc, parts.path, clean(parts.query), clean(parts.fragment))
    )
    return url if cleaned == urlunsplit(parts) else cleaned


def _without_credentials(record: BaseModel) -> BaseModel:
    update = {}
    for name in ("url", "start_url"):
        value = getattr(record, name, None)
        if isinstance(value, str) and hide_credentials(value) != value:
            update[name] = hide_credentials(value)
    if (
        isinstance(record, TraceEvent)
        and record.type == "navigate"
        and record.value
        and hide_credentials(record.value) != record.value
    ):
        update["value"] = hide_credentials(record.value)
    return record.model_copy(update=update) if update else record


class TraceWriter:
    """Appends records and flushes each one, so a crash loses at most the current line. An
    address is written without what signs in (``hide_credentials``)."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file: IO[str] = path.open("w", encoding="utf-8", newline="\n")

    def write(self, record: BaseModel) -> None:
        record = _without_credentials(record)
        self._file.write(record.model_dump_json(exclude_none=True) + "\n")
        self._file.flush()

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    @property
    def closed(self) -> bool:
        return self._file.closed

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
    """Read a trace (a trace.jsonl file or the folder containing one) and check it.

    A recording cut off (the computer stopped, the recorder failed) has no end record: its
    last line may be written only in part, and its last events may name a screen that was
    not written yet. What it has is read; a whole recording that says otherwise is refused.
    Lines are split at line ends only: a text may hold U+2028 (a line separator)."""
    path = Path(path)
    file = path / "trace.jsonl" if path.is_dir() else path
    trace: Trace | None = None
    lines = [
        (number, line)
        for number, line in enumerate(file.read_text(encoding="utf-8").split("\n"), start=1)
        if line.strip()
    ]
    trailing = 0
    """Events written after the last screen: a recording cut off there may name its next."""
    for index, (number, line) in enumerate(lines):
        try:
            if trace is None:
                _check_format(line, file)
            record = _RECORD.validate_json(line)
        except ValidationError as exc:
            if trace is not None and trace.end is None and index == len(lines) - 1 and _cut(line):
                break  # the line being written when the recording stopped
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
            trailing += 1
        elif isinstance(record, TraceState):
            if record.id in trace.states:
                raise TraceError(f"{file}:{number}: state '{record.id}' appears twice")
            trace.states[record.id] = record
            trailing = 0
        elif isinstance(record, TraceEnd):
            trace.end = record
    if trace is None:
        raise TraceError(f"{file}: empty trace")
    cut_off = trace.end is None and bool(trace.states)
    first_trailing = len(trace.events) - trailing
    for index, event in enumerate(trace.events):
        refs = (event.state_before, event.state_after)
        missing = [ref for ref in refs if ref is not None and ref not in trace.states]
        if not missing:
            continue
        if cut_off and index >= first_trailing:  # the screen it names was not written yet
            known = {k: getattr(event, k) in trace.states for k in ("state_before", "state_after")}
            update = {k: None for k, ok in known.items() if not ok}
            trace.events[index] = event.model_copy(update=update)
            continue
        raise TraceError(f"{file}: event {event.seq} refers to unknown state '{missing[0]}'")
    return trace


def _check_format(line: str, file: Path) -> None:
    """A recording made by a newer Maptelo is refused with a sentence that says so."""
    try:
        header = json.loads(line)
    except ValueError:
        return
    if isinstance(header, dict):
        try:
            upgraded(header, "format", TRACE_VERSIONS, "the recording")
        except NewerFormatError as exc:
            raise TraceError(f"{file}: {exc}") from exc


def _cut(line: str) -> bool:
    """A line written only in part: no whole JSON record."""
    try:
        json.loads(line)
    except ValueError:
        return True
    return False
