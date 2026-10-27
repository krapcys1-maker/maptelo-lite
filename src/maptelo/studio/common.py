"""What every part of Studio shares: the browsers a person can choose, the problems a request
has before any work starts (said back on the page, each in its own sentence), and the page's
language as the person chose it."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool

from maptelo.files import write_atomic
from maptelo.mapping.naming import Lang

BROWSERS = {"chromium": None, "msedge": "msedge", "chrome": "chrome"}
"""The browsers offered, by name: Playwright's own Chromium, or the company's Edge or Chrome."""


class RunProblemError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _settings() -> Path:
    from maptelo import browser  # its HOME is where this person's things are (MAPTELO_HOME)

    return browser.HOME / "studio.json"


def page_language() -> Lang | None:
    """The page's language as the person last chose it (Maptelo Lite), if they did. Kept with
    the profiles: the window's address changes at every start, and with it the browser's own
    storage."""
    try:
        said = json.loads(_settings().read_text(encoding="utf-8")).get("lang")
    except (OSError, ValueError, AttributeError):
        return None
    if said == "pl":
        return "pl"
    return "en" if said == "en" else None


def keep_page_language(lang: Lang) -> None:
    path = _settings()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps({"lang": lang}), encoding="utf-8")


_LOCKS: dict[Path, threading.Lock] = {}
_GUARD = threading.Lock()


def _workspace_lock(root: Path) -> threading.Lock:
    with _GUARD:
        return _LOCKS.setdefault(root, threading.Lock())


async def off_loop[T](root: Path, work: Callable[..., T], *args: Any) -> T:
    """Work that takes a while (a map made, a model built, a sheet read) done beside the
    server, so that the page and every other request are answered meanwhile; one such work
    at a time in a workspace, as they write the same files."""
    lock = _workspace_lock(root)

    def locked() -> T:
        with lock:
            return work(*args)

    return await run_in_threadpool(locked)
