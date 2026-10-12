"""Work that takes a while (a run through a sheet) happens in its own thread, one at a time.

Each job keeps a numbered list of events; the page asks for the ones after the last it has
seen. One at a time because a job drives a browser with the person's profile, and two
browsers on one profile cannot work.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


class BusyError(Exception):
    def __init__(self, job: Job) -> None:
        super().__init__(f"{job.title} is still running")
        self.job = job


@dataclass
class Job:
    id: str
    kind: str
    title: str
    process: str | None
    started: float = field(default_factory=time.time)
    state: str = "running"
    """running | done | stopped | failed"""
    result: dict[str, Any] | None = None
    error: str | None = None
    stop_requested: bool = False
    _events: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, kind: str, **data: Any) -> None:
        with self._lock:
            self._events.append(
                {"seq": len(self._events) + 1, "type": kind, "at": time.time(), **data}
            )

    def view(self, after: int | None = 0) -> dict[str, Any]:
        """The job, with its events after number ``after`` (None: without events)."""
        with self._lock:
            events = [] if after is None else self._events[after:]
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "process": self.process,
            "started": self.started,
            "state": self.state,
            "stop_requested": self.stop_requested,
            "result": self.result,
            "error": self.error,
            "events": events,
        }


class Jobs:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._current: Job | None = None

    def start(
        self,
        kind: str,
        title: str,
        work: Callable[[Job], dict[str, Any]],
        *,
        process: str | None = None,
    ) -> Job:
        with self._lock:
            if self._current is not None and self._current.state == "running":
                raise BusyError(self._current)
            job = Job(secrets.token_hex(6), kind, title, process)
            self._jobs[job.id] = job
            self._current = job
        threading.Thread(
            target=self._run, args=(job, work), name=f"job-{job.id}", daemon=True
        ).start()
        return job

    @staticmethod
    def _run(job: Job, work: Callable[[Job], dict[str, Any]]) -> None:
        try:
            job.result = work(job)
            job.state = "stopped" if job.stop_requested else "done"
        except Exception as exc:  # the page shows it; the server keeps serving
            log.exception("job %s failed", job.id)
            job.error = str(exc) or type(exc).__name__
            job.state = "failed"
        job.emit("end", state=job.state, error=job.error)

    def get(self, job_id: str) -> Job:
        return self._jobs[job_id]

    @property
    def current(self) -> Job | None:
        return self._current

    def wait(self, job_id: str, timeout: float) -> Job:
        """Until the job ends (or the time is up)."""
        deadline = time.monotonic() + timeout
        job = self.get(job_id)
        while job.state == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
        return job

    def shutdown(self, timeout: float = 120) -> None:
        """Studio is closing: the running job stops after its current record, which is let
        finish (a record cut in the middle could leave the application half-edited)."""
        current = self._current
        if current is not None and current.state == "running":
            current.stop_requested = True
            self.wait(current.id, timeout)
