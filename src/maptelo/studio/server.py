"""Start Studio: the server on 127.0.0.1, and its page in a window of its own (or in the
browser of this computer). Closing the window closes Studio.

When Studio closes, a run going on is asked to stop: the record in progress is let finish,
so no application is left half-edited, and the rest waits for the next run.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import threading
import time
import webbrowser
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from maptelo.files import write_atomic
from maptelo.logs import keep_log
from maptelo.policy import PolicyError
from maptelo.policy import current as current_policy
from maptelo.retention import sweep
from maptelo.studio.app import create_app
from maptelo.studio.jobs import Jobs
from maptelo.studio.window import open_window, watch
from maptelo.studio.workspace import Workspace

INSTANCE = "studio-instance.json"
"""In the data folder: the address of the Studio (or Lite) running on it. Its window's browser
profile is there too, so a second one would take the first one's window."""


def running_instance(home: Path) -> str | None:
    """The address (with its key) of the Studio already running on this data folder, if one
    answers there."""
    try:
        said = json.loads((home / INSTANCE).read_text(encoding="utf-8"))
        address, port = str(said["address"]), int(said["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return address
    except OSError:
        return None  # it stopped without saying so (the computer was switched off)


def _claim(home: Path, address: str, port: int) -> Path:
    path = home / INSTANCE
    home.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps({"address": address, "port": port, "pid": os.getpid()}))
    return path


def _release(path: Path, address: str) -> None:
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("address") == address:
            path.unlink()
    except (OSError, ValueError, AttributeError):
        pass


def _show(address: str, window: bool, announce: Callable[[str], None]) -> bool:
    """The page in a window of its own, else in the default browser; whether a window."""
    if window and open_window(address):
        return True
    if window:
        announce("no Edge or Chrome for a window here: the page opens in the default browser")
    webbrowser.open(address)
    return False


def _listen(port: int) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", port))
    return listener


def _server(
    workspace: Workspace,
    token: str,
    jobs: Jobs,
    opener: Callable[[Path], None] | None,
    *,
    lite: bool = False,
) -> uvicorn.Server:
    if opener is None:
        app = create_app(workspace, token, jobs, lite=lite)
    else:
        app = create_app(workspace, token, jobs, opener=opener, lite=lite)
    return uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))


def _keep_only_what_policy_allows(workspace: Workspace, announce: Callable[[str], None]) -> None:
    """When IT's policy says how long screenshots are kept, Studio removes older ones."""
    try:
        days = current_policy().rules.evidence.keep_days
    except PolicyError:
        return  # an unreadable policy stops runs; it is not read here
    if days is not None:
        swept = sweep(workspace.root, days)
        if swept.removed:
            announce(f"removed {len(swept.removed)} evidence files older than {days} days (policy)")


def serve(
    workspace: Workspace,
    *,
    port: int = 0,
    open_page: bool = True,
    window: bool = True,
    announce: Callable[[str], None] = print,
    lite: bool = False,
) -> None:
    """Serve until stopped (Ctrl+C, or the window closed). The address carries a one-time
    key for this start. ``lite``: Maptelo Lite (maps only, no robot)."""
    keep_log("maptelo-lite" if lite else "maptelo-studio")
    from maptelo.browser import HOME

    already = running_instance(HOME)
    if already is not None:  # its window opens again, nothing else starts
        announce(f"{'Maptelo Lite' if lite else 'Studio'} is already running: {already}")
        if open_page:
            _show(already, window, announce)
        return
    token = secrets.token_urlsafe(24)
    listener = _listen(port)
    address = f"http://127.0.0.1:{listener.getsockname()[1]}/?t={token}"
    claimed = _claim(HOME, address, listener.getsockname()[1])
    jobs = Jobs()
    server = _server(workspace, token, jobs, None, lite=lite)
    threading.Thread(target=_keep_only_what_policy_allows, args=(workspace, announce),
                     name="studio-retention", daemon=True).start()  # fmt: skip

    def when_ready() -> None:
        while not server.started and not server.should_exit:
            time.sleep(0.05)
        if not server.started:
            return
        announce(address)
        if not open_page:
            return
        if _show(address, window, announce):

            def close() -> None:
                announce("the window was closed: Studio stops")
                server.should_exit = True

            if not watch(close):  # no window to close: a page a person can see, and stop
                announce("the window did not show up: the page opens in the default browser")
                webbrowser.open(address)

    threading.Thread(target=when_ready, name="studio-open", daemon=True).start()
    try:
        server.run(sockets=[listener])
    finally:
        jobs.shutdown()
        _release(claimed, address)


@contextmanager
def running(
    workspace: Workspace,
    token: str,
    *,
    port: int = 0,
    opener: Callable[[Path], None] | None = None,
    lite: bool = False,
) -> Iterator[str]:
    """Studio in its own thread while the block runs; gives its address (without the key)."""
    listener = _listen(port)
    jobs = Jobs()
    server = _server(workspace, token, jobs, opener, lite=lite)
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, name="studio", daemon=True
    )
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("Studio did not start")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        jobs.shutdown()
        server.should_exit = True
        thread.join(timeout=15)
