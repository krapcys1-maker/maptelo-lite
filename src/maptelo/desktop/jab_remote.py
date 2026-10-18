"""The Java Access Bridge through a helper Python of the bridge library's bitness.

A program loads only libraries of its own bitness. A computer with only a 32-bit Java (7 or 8,
as many Oracle Forms installations have) has only ``WindowsAccessBridge-32.dll``, which a
64-bit Python (Maptelo Lite's) cannot load. There the bridge works in a helper process: a
Python of the library's bitness runs ``serve``, which starts a ``Bridge`` and answers one JSON
line per question on its standard output; the bridge's events follow on the same output as
they come. ``RemoteBridge`` asks what ``Bridge`` answers and gives back the same answers, so
recording and running do not know the difference.

The helper Python is the one ``MAPTELO_PYTHON32`` names, the one shipped beside this one
(Maptelo Lite's ``python32`` folder), or the newest one installed and registered in Windows.
It imports this module and ``jab`` from Maptelo's own folder, after its own standard library.
Nothing is copied or renamed, and nothing needs administrator rights.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import fields, replace
from pathlib import Path
from typing import IO, Any, TypeVar

from maptelo.desktop.jab import (
    AccessBridgeError,
    Bridge,
    Node,
    StaleNodeError,
    Table,
    Window,
    pe_bits,
    python_bits,
)

T = TypeVar("T")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
"""The folder Maptelo's package is in (site-packages, or src in a checkout)."""

BOOT = (
    "import sys; sys.path.append(sys.argv[1]); "
    "from maptelo.desktop.jab_remote import serve; serve()"
)
"""What the helper Python runs (``-I``: nothing from the environment or the user's folders):
its own standard library first, Maptelo's folder after it."""

OLDEST = (3, 12)
"""The oldest Python the helper runs on: the one Maptelo itself needs."""

ASKED = frozenset(
    {
        "windows",
        "tree",
        "focus",
        "has_focus",
        "node",
        "children_selected",
        "table",
        "table_cell",
        "request_focus",
        "set_text",
        "select_all_text",
        "select",
        "clear_selection",
        "do_action",
    }
)
"""What the helper answers: the bridge's questions and acts (its events come by themselves)."""

WAIT_MORE = 15.0
"""How much longer than the bridge's own limit an answer is waited for here."""


# -- the helper Python ------------------------------------------------------------------------


def helper_python(bits: int) -> Path | None:
    """A Python of the given bitness to run the helper: the one ``MAPTELO_PYTHON32`` (or
    ``..64``) names, the one shipped beside this one (``python32`` next to Maptelo Lite's
    ``python``), then the newest registered in Windows. None: there is none here."""
    candidates: list[Path] = []
    named = os.environ.get(f"MAPTELO_PYTHON{bits}")
    if named:
        candidates.append(Path(named))
    candidates.append(Path(sys.prefix).parent / f"python{bits}" / "python.exe")
    candidates += registered_pythons(bits)
    return next((path for path in candidates if pe_bits(path) == bits), None)


def registered_pythons(bits: int) -> list[Path]:
    """The Pythons of that bitness installed and registered in Windows (PEP 514), newest
    first; only those the helper runs on."""
    if sys.platform != "win32":
        return []
    import winreg

    found: dict[Path, tuple[int, ...]] = {}
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            access = winreg.KEY_READ | view
            try:
                core = winreg.OpenKey(hive, r"Software\Python\PythonCore", 0, access)
            except OSError:
                continue
            with core:
                for index in itertools.count():
                    try:
                        tag = winreg.EnumKey(core, index)
                    except OSError:
                        break
                    version = tuple(int(n) for n in re.findall(r"\d+", tag)[:2])
                    if version < OLDEST:
                        continue
                    try:
                        with winreg.OpenKey(core, rf"{tag}\InstallPath", 0, access) as key:
                            folder = str(winreg.QueryValueEx(key, "")[0])
                    except OSError:
                        continue
                    path = Path(folder) / "python.exe"
                    if pe_bits(path) == bits:
                        found[path] = version
    return sorted(found, key=lambda path: found[path], reverse=True)


def native_handle(value: int) -> int:
    """A window handle as this process holds it. Between 32-bit and 64-bit programs only its
    low 32 bits count; a 64-bit program holds them sign-extended."""
    low = value & 0xFFFF_FFFF
    if python_bits() == 64 and low & 0x8000_0000:
        return low | 0xFFFF_FFFF_0000_0000
    return low


# -- what goes through the pipe -----------------------------------------------------------------

_TYPES: dict[str, Any] = {"Node": Node, "Window": Window, "Table": Table}


def pack(value: Any) -> Any:
    """A question or an answer as JSON. Nodes, windows, tables, tuples and sets are marked,
    so that ``unpack`` gives back the very types (a frame chain is a list of tuples)."""
    if isinstance(value, Node | Window | Table):
        kind = type(value).__name__
        return {f"${kind}": {f.name: pack(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, tuple):
        return {"$tuple": [pack(item) for item in value]}
    if isinstance(value, frozenset):
        return {"$frozenset": sorted(value)}
    if isinstance(value, list):
        return [pack(item) for item in value]
    if isinstance(value, dict):
        return {key: pack(item) for key, item in value.items()}
    return value


def unpack(value: Any) -> Any:
    if isinstance(value, list):
        return [unpack(item) for item in value]
    if not isinstance(value, dict):
        return value
    if len(value) == 1:
        ((key, inner),) = value.items()
        if key == "$tuple":
            return tuple(unpack(item) for item in inner)
        if key == "$frozenset":
            return frozenset(inner)
        if key.startswith("$") and key[1:] in _TYPES:
            return _TYPES[key[1:]](**{name: unpack(item) for name, item in inner.items()})
    return {key: unpack(item) for key, item in value.items()}


def _line(message: dict[str, Any]) -> bytes:
    """One message, one line. ASCII: a Java text may hold half of a UTF-16 pair."""
    return json.dumps(message).encode("ascii") + b"\n"


# -- the helper's side --------------------------------------------------------------------------


def serve() -> None:
    """The helper process (started by RemoteBridge): it answers until it is told to close or
    this process's input ends, then leaves at once. A bridge call still waiting for the Java
    program must not keep it alive, and neither may the library's own way out."""
    source, sink = sys.stdin.buffer, sys.stdout.buffer
    sys.stdout = sys.stderr  # what is printed goes to the log, never between the answers
    print(
        f"Helper: Python {sys.version.split()[0]} ({python_bits()}-bit), {sys.executable}",
        file=sys.stderr,
        flush=True,
    )
    answer_all(source, sink)
    sys.stderr.flush()
    os._exit(0)


def answer_all(source: IO[bytes], sink: IO[bytes], *, make: Callable[..., Bridge] = Bridge) -> None:
    """Answer the questions read from ``source`` on ``sink``, one line each, until ``close`` or
    the end of ``source``. Each question is answered in its own thread, as each caller of a
    ``Bridge`` waits for its own answer. ``make``: the bridge (tests give a stand-in)."""
    lock = threading.Lock()

    def say(message: dict[str, Any]) -> None:
        with lock:
            sink.write(_line(message))
            sink.flush()

    bridge: Bridge | None = None
    for line in iter(source.readline, b""):
        try:
            question = json.loads(line)
        except ValueError:
            continue
        op = question.get("op")
        if op == "start" and bridge is None:
            bridge = _start(make, question, say)
        elif op == "close":
            if bridge is not None:
                bridge.close()
            say({"id": question.get("id"), "result": None})
            return
        else:
            threading.Thread(target=_answer, args=(bridge, question, say), daemon=True).start()


def _start(
    make: Callable[..., Bridge], question: dict[str, Any], say: Callable[[dict[str, Any]], None]
) -> Bridge:
    options = question.get("options") or {}
    bridge = make(
        java_dirs=[Path(folder) for folder in options.get("java_dirs") or []],
        desktop=options.get("desktop"),
        events=bool(options.get("events")),
    )
    try:
        bridge.start(float(options.get("timeout") or 10.0))
    except AccessBridgeError as exc:
        print(f"Helper: {exc}", file=sys.stderr, flush=True)
        say({"id": question.get("id"), "error": type(exc).__name__, "message": str(exc)})
        return bridge
    print(f"Helper: the library {bridge.dll_path} answers", file=sys.stderr, flush=True)
    if bridge.want_events:
        threading.Thread(target=_forward, args=(bridge, say), daemon=True).start()
    say(
        {
            "id": question.get("id"),
            "result": {"dll": str(bridge.dll_path), "clock": bridge.clock(), "now": time.time()},
        }
    )
    return bridge


def _forward(bridge: Bridge, say: Callable[[dict[str, Any]], None]) -> None:
    """The bridge's events as they come (each holds the time it was told at), then the time
    up to which all were told (``Bridge.delivered``), until the other side is gone."""
    told = -1.0
    while True:
        try:
            through = bridge.delivered()  # first: the events told by then are taken below
            for event in bridge.events():
                say({"event": pack(event)})
            if through != told:
                say({"through": through})
                told = through
        except (OSError, ValueError):
            return
        time.sleep(0.01)


def _answer(
    bridge: Bridge | None, question: dict[str, Any], say: Callable[[dict[str, Any]], None]
) -> None:
    reply: dict[str, Any] = {"id": question.get("id")}
    try:
        op = question.get("op")
        if bridge is None or not bridge.ready or op not in ASKED:
            raise AccessBridgeError(bridge.status if bridge is not None else "not started")
        args = unpack(question.get("args") or [])
        if args and op != "windows":
            args[0] = native_handle(int(args[0]))
        reply["result"] = pack(getattr(bridge, op)(*args, **unpack(question.get("kwargs") or {})))
    except AccessBridgeError as exc:
        reply.update(error=type(exc).__name__, message=str(exc))
    except Exception as exc:  # a fault here: the caller hears of it, its trace goes to the log
        traceback.print_exc(file=sys.stderr)
        reply.update(error=type(exc).__name__, message=f"{type(exc).__name__}: {exc}")
    reply["stuck"] = bool(getattr(bridge, "stuck", False))
    with contextlib.suppress(OSError, ValueError):  # the other side is gone
        say(reply)


# -- this process's side --------------------------------------------------------------------------


class RemoteBridge(Bridge):
    """The bridge in a helper Python of the library's bitness (see the module): the questions
    and answers of ``Bridge``, each a line to the helper and one back."""

    def __init__(
        self,
        python: Path,
        *,
        java_dirs: list[Path] | None = None,
        desktop: str | None = None,
        events: bool = False,
    ) -> None:
        super().__init__(java_dirs=java_dirs, desktop=desktop, events=events)
        self.python = python
        self.stuck = False
        self._process: subprocess.Popen[bytes] | None = None
        self._writing = threading.Lock()
        self._ids = itertools.count(1)
        self._waiting: dict[int, tuple[threading.Event, list[dict[str, Any]]]] = {}
        self._said: list[str] = []

    # -- life ------------------------------------------------------------------------------------

    def start(self, timeout: float = 10.0) -> RemoteBridge:
        if self._process is not None:
            return self
        self.status = f"starting the helper Python {self.python}"
        self._process = self._spawn()
        threading.Thread(target=self._listen, name="java-bridge-helper", daemon=True).start()
        threading.Thread(target=self._relay, name="java-bridge-helper-log", daemon=True).start()
        options = {
            "java_dirs": [str(folder) for folder in self.java_dirs],
            "desktop": self.desktop,
            "events": self.want_events,
            "timeout": timeout,
        }
        try:
            started = self._exchange({"op": "start", "options": options}, timeout + WAIT_MORE)
        except AccessBridgeError:
            self._end()
            raise
        self.dll_path = Path(started["dll"])
        self._t0 = float(started["now"]) - float(started["clock"])
        self.ready = True
        self.status = "ready"
        log.info(
            "Java Access Bridge %s through the %d-bit Python %s",
            self.dll_path,
            pe_bits(self.python) or 0,
            self.python,
        )
        return self

    def close(self) -> None:
        if self._process is None:
            return
        if self.ready and not self.stuck:
            with contextlib.suppress(AccessBridgeError):
                self._exchange({"op": "close"}, 10.0)
        self._end()

    def _spawn(self) -> subprocess.Popen[bytes]:
        try:
            return subprocess.Popen(
                [str(self.python), "-I", "-c", BOOT, str(ROOT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.python.parent),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise AccessBridgeError(
                f"the helper Python {self.python} does not start: {exc}"
            ) from exc

    def _end(self) -> None:
        """The helper is let go: its input closed, so it leaves; one still waiting for the
        Java program is stopped."""
        process, self._process = self._process, None
        self.ready = False
        if process is None:
            return
        with contextlib.suppress(OSError):
            if process.stdin is not None:
                process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    # -- the pipe ----------------------------------------------------------------------------------

    def _listen(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in iter(process.stdout.readline, b""):
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if "event" in message:
                self._events.put(self._ours(unpack(message["event"])))
                continue
            if "through" in message:  # after the events it covers: they are queued already
                self._delivered = float(message["through"])
                continue
            waiting = self._waiting.pop(message.get("id"), None)
            if waiting is not None:
                done, box = waiting
                box.append(message)
                done.set()
        # the helper ended: no answer comes to those still waiting
        self.ready = False
        self.status = f"the helper of the Java Access Bridge ended{self._last_words()}"
        for done, _ in list(self._waiting.values()):
            done.set()

    def _relay(self) -> None:
        """What the helper writes to its standard error (which Python, which library, a fault's
        trace) goes to Maptelo's log."""
        process = self._process
        if process is None or process.stderr is None:
            return
        for raw in iter(process.stderr.readline, b""):
            text = raw.decode("utf-8", "replace").rstrip()
            if text:
                self._said = [*self._said[-19:], text]
                log.info("Java Access Bridge %s", text)

    def _last_words(self) -> str:
        last = next((line for line in reversed(self._said) if line.startswith("Helper: ")), None)
        return f" ({last.removeprefix('Helper: ')})" if last else ""

    def _exchange(self, message: dict[str, Any], wait: float) -> Any:
        process = self._process
        if process is None or process.stdin is None:
            raise AccessBridgeError(self.status)
        number = next(self._ids)
        done = threading.Event()
        box: list[dict[str, Any]] = []
        self._waiting[number] = (done, box)
        try:
            with self._writing:
                process.stdin.write(_line({"id": number, **message}))
                process.stdin.flush()
        except OSError as exc:
            self._waiting.pop(number, None)
            raise AccessBridgeError(
                f"the helper of the Java Access Bridge ended{self._last_words()}"
            ) from exc
        if not done.wait(wait):
            self._waiting.pop(number, None)
            self.stuck = True  # as the bridge's own thread: nothing else passes now
            raise AccessBridgeError(
                "the Java program does not answer (a window it opened may be waiting)"
            )
        if not box:
            raise AccessBridgeError(self.status)
        answer = box[0]
        self.stuck = self.stuck or bool(answer.get("stuck"))
        if "error" in answer:
            kind = StaleNodeError if answer["error"] == "StaleNodeError" else AccessBridgeError
            raise kind(str(answer.get("message") or answer["error"]))
        return unpack(answer.get("result"))

    def _ask(self, op: str, *args: Any, wait: float = 30.0, **kwargs: Any) -> Any:
        if not self.ready:
            raise AccessBridgeError(self.status)
        if self.stuck:
            raise AccessBridgeError(
                "the Java program still does not answer (a window it opened may be waiting)"
            )
        question = {"op": op, "args": pack(list(args)), "kwargs": pack(kwargs)}
        return self._exchange(question, wait + WAIT_MORE)

    def _ours(self, event: dict[str, Any]) -> dict[str, Any]:
        source = event.get("source")
        if isinstance(source, dict) and source.get("window"):
            source["window"] = native_handle(int(source["window"]))
        return event

    # -- what Bridge answers ---------------------------------------------------------------------

    def call(self, task: Callable[[], T], timeout: float = 30.0) -> T:
        raise NotImplementedError("RemoteBridge answers the questions of Bridge only")

    def windows(self, *, pid: int | None = None, java_only: bool = True) -> list[Window]:
        found: list[Window] = self._ask("windows", pid=pid, java_only=java_only)
        return [replace(w, hwnd=native_handle(w.hwnd), owner=native_handle(w.owner)) for w in found]

    def tree(
        self,
        hwnd: int,
        *,
        limit: int = 8000,
        showing_only: bool = True,
        texts: bool = True,
        prune: Callable[[Node], bool] | None = None,
        root: str = "0",
        actions: bool = True,
    ) -> list[Node]:
        if prune is not None:
            raise NotImplementedError("RemoteBridge reads whole trees (no prune)")
        nodes: list[Node] = self._ask(
            "tree",
            hwnd,
            limit=limit,
            showing_only=showing_only,
            texts=texts,
            root=root,
            actions=actions,
            wait=60.0,
        )
        return nodes

    def delivered(self) -> float:
        """As the helper's bridge tells it after the events it covers (``Bridge.delivered``)."""
        if not self.want_events:
            return self.clock()
        return self._delivered

    def focus(self, hwnd: int) -> tuple[Node, list[tuple[str, str]], int] | None:
        found = self._ask("focus", hwnd)
        if found is None:
            return None
        node, chain, top = found
        return node, chain, native_handle(top)

    def has_focus(self, hwnd: int, path: str) -> bool:
        return bool(self._ask("has_focus", hwnd, path))

    def node(self, hwnd: int, path: str) -> Node | None:
        found: Node | None = self._ask("node", hwnd, path)
        return found

    def children_selected(
        self, hwnd: int, path: str, count: int, *, first: bool = False
    ) -> list[int]:
        chosen: list[int] = self._ask("children_selected", hwnd, path, count, first=first)
        return chosen

    def table(self, hwnd: int, path: str, *, max_rows: int = 500) -> Table | None:
        found: Table | None = self._ask("table", hwnd, path, max_rows=max_rows, wait=60.0)
        return found

    def table_cell(self, hwnd: int, path: str, row: int, column: int) -> Node | None:
        found: Node | None = self._ask("table_cell", hwnd, path, row, column)
        return found

    def request_focus(self, hwnd: int, path: str, expect: Node | None = None) -> bool:
        return bool(self._ask("request_focus", hwnd, path, expect))

    def set_text(self, hwnd: int, path: str, text: str, expect: Node | None = None) -> bool:
        return bool(self._ask("set_text", hwnd, path, text, expect))

    def select_all_text(self, hwnd: int, path: str, expect: Node | None = None) -> bool:
        return bool(self._ask("select_all_text", hwnd, path, expect))

    def select(
        self, hwnd: int, path: str, index: int, expect: Node | None = None, *, clear: bool = True
    ) -> None:
        self._ask("select", hwnd, path, index, expect, clear=clear)

    def clear_selection(self, hwnd: int, path: str, expect: Node | None = None) -> None:
        self._ask("clear_selection", hwnd, path, expect)

    def do_action(self, hwnd: int, path: str, action: str, expect: Node | None = None) -> bool:
        return bool(self._ask("do_action", hwnd, path, action, expect, wait=10.0))
