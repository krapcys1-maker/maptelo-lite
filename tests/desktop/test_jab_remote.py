"""A 32-bit Java's bridge through a helper Python of its bitness: what goes through the pipe
comes back as it was, the helper answers as the bridge does (its events too), the library
of the right bitness is found, and the helper Python is the one shipped, named or installed."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from maptelo.desktop import jab, jab_remote
from maptelo.desktop.jab import (
    AccessBridgeError,
    Bridge,
    BridgeLibrary,
    Node,
    StaleNodeError,
    Table,
    Window,
)
from maptelo.desktop.jab_remote import RemoteBridge, answer_all, native_handle, pack, unpack

FIELD = Node(
    path="0/1/2",
    role="text",
    name="Kontrahent",
    description="Kod kontrahenta",
    states=frozenset({"enabled", "focusable", "showing"}),
    box=(10, 20, 100, 30),
    children=0,
    index=2,
    text="K0001",
    interfaces=3,
    actions=("click",),
)
WINDOW = Window(0x0005_0ABC, "SRK 4.2 - System Rozliczeń", 77, True, 0, (0, 0, 800, 600))
CHAIN = [("internal frame", "Cennik klienta"), ("frame", "SRK")]
EVENT = {
    "kind": "focus",
    "t": 0.5,
    "source": {"node": FIELD.to_dict(), "chain": CHAIN, "window": WINDOW.hwnd},
}
JRE8 = Path("C:/Program Files (x86)/Java/jre8/bin")


def through_the_pipe(value: Any) -> Any:
    return unpack(json.loads(json.dumps(pack(value))))


def test_what_goes_through_the_pipe_comes_back_as_it_was() -> None:
    table = Table(["Indeks", "Cena"], [["26386", "4,26"], ["37241", "64,69"]], [1])
    focus = (FIELD, CHAIN, WINDOW.hwnd)
    broken = Node("0", "text", "Uwagi", text="half of a pair: \ud800")  # Java's UTF-16 allows it
    for value in (FIELD, WINDOW, table, focus, EVENT, [FIELD, broken], None, True, 4, "Zażółć"):
        assert through_the_pipe(value) == value
    node, chain, _ = through_the_pipe(focus)
    assert isinstance(node.states, frozenset)
    assert isinstance(node.box, tuple)
    assert all(isinstance(frame, tuple) for frame in chain)  # as the bridge gives a chain


def test_a_window_handle_keeps_its_low_32_bits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jab_remote, "python_bits", lambda: 64)
    assert native_handle(0x0005_0ABC) == 0x0005_0ABC
    assert native_handle(0x8005_0ABC) == 0xFFFF_FFFF_8005_0ABC  # sign-extended in 64 bits
    monkeypatch.setattr(jab_remote, "python_bits", lambda: 32)
    assert native_handle(0xFFFF_FFFF_8005_0ABC) == 0x8005_0ABC


def program_file(folder: Path, name: str, machine: int) -> Path:
    """A file with just the headers of a Windows program built for ``machine``."""
    folder.mkdir(parents=True, exist_ok=True)
    head = bytearray(0x80)
    head[:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 0x40)
    head[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<H", head, 0x44, machine)
    path = folder / name
    path.write_bytes(bytes(head))
    return path


X86, X64, ARM64 = 0x014C, 0x8664, 0xAA64


def test_a_library_tells_its_bitness_by_its_header(tmp_path: Path) -> None:
    assert jab.pe_bits(program_file(tmp_path, "a.dll", X86)) == 32
    assert jab.pe_bits(program_file(tmp_path, "b.dll", X64)) == 64
    assert jab.pe_bits(program_file(tmp_path, "c.dll", ARM64)) is None
    (tmp_path / "d.dll").write_bytes(b"not a program")
    assert jab.pe_bits(tmp_path / "d.dll") is None
    assert jab.pe_bits(tmp_path / "missing.dll") is None
    if sys.platform == "win32":
        assert jab.pe_bits(Path(sys.executable)) == jab.python_bits()


@pytest.fixture
def no_java(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A computer whose only Java is what the test puts in the folder it returns."""
    for name in ("JAVA_HOME", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("WINDIR", str(tmp_path / "Windows"))
    return tmp_path / "jre8" / "bin"


def test_a_32_bit_java_has_only_the_32_bit_library(no_java: Path) -> None:
    library = program_file(no_java, "WindowsAccessBridge-32.dll", X86)
    assert jab.find_dll([no_java], 64) is None
    assert jab.find_dll([no_java], 32) == library
    program_file(no_java, "WindowsAccessBridge-64.dll", X86)  # named 64, built for 32
    assert jab.find_dll([no_java], 64) is None


def test_windows_own_folder_of_each_bitness(no_java: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    windows = no_java.parents[1] / "Windows"
    monkeypatch.setattr(jab, "python_bits", lambda: 64)
    assert windows / "SysWOW64" in jab.candidate_dirs(bits=32)
    assert windows / "System32" in jab.candidate_dirs(bits=64)
    monkeypatch.setattr(jab, "python_bits", lambda: 32)
    assert windows / "System32" in jab.candidate_dirs(bits=32)
    assert windows / "Sysnative" in jab.candidate_dirs(bits=64)


def test_the_bridge_library_and_the_python_that_loads_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ours, theirs = tmp_path / "WindowsAccessBridge-64.dll", JRE8 / "WindowsAccessBridge-32.dll"
    helper = tmp_path / "python32" / "python.exe"
    found: dict[int, Path | None] = {64: None, 32: theirs}
    monkeypatch.setattr(jab, "python_bits", lambda: 64)
    monkeypatch.setattr(jab, "find_dll", lambda extra=None, bits=None: found[bits or 64])
    monkeypatch.setattr(jab_remote, "helper_python", lambda bits: helper if bits == 32 else None)
    assert jab.bridge_library() == BridgeLibrary(theirs, 32, helper)
    assert jab.bridge_library().usable  # type: ignore[union-attr]
    monkeypatch.setattr(jab_remote, "helper_python", lambda bits: None)
    lacking = jab.bridge_library()
    assert lacking == BridgeLibrary(theirs, 32, None)
    assert not lacking.usable
    assert jab.no_helper(lacking).startswith(
        "the Java here has only WindowsAccessBridge-32.dll (32-bit), which this 64-bit Python "
        "cannot load"
    )
    found[64] = ours
    assert jab.bridge_library() == BridgeLibrary(ours, 64)
    found[64] = found[32] = None
    assert jab.bridge_library() is None


def test_connect_starts_the_bridge_where_its_library_loads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started: list[tuple[str, Any]] = []

    class Here:
        def __init__(self, **options: Any) -> None:
            self.options = options

        def start(self, timeout: float = 10.0) -> Here:
            started.append(("here", self.options["java_dirs"]))
            return self

    class Helper(Here):
        def __init__(self, python: Path, **options: Any) -> None:
            super().__init__(**options)
            self.python = python

        def start(self, timeout: float = 10.0) -> Helper:
            started.append(("helper", self.python))
            return self

    helper = tmp_path / "python32" / "python.exe"
    monkeypatch.setattr(jab, "Bridge", Here)
    monkeypatch.setattr(jab_remote, "RemoteBridge", Helper)
    monkeypatch.setattr(jab, "python_bits", lambda: 64)
    answers = iter(
        [
            BridgeLibrary(tmp_path / "WindowsAccessBridge-64.dll", 64),
            BridgeLibrary(JRE8 / "WindowsAccessBridge-32.dll", 32, helper),
            None,
            BridgeLibrary(JRE8 / "WindowsAccessBridge-32.dll", 32, None),
        ]
    )
    monkeypatch.setattr(jab, "bridge_library", lambda extra=None: next(answers))
    jab.connect(java_dirs=[JRE8])
    jab.connect(java_dirs=[JRE8], events=True)
    jab.connect()  # no library at all: the bridge says so as it starts
    with pytest.raises(AccessBridgeError, match="no Python of its bitness was found"):
        jab.connect()
    assert started == [("here", [JRE8]), ("helper", helper), ("here", None)]


# -- the helper, behind pipes -----------------------------------------------------------------


class Program:
    """A Java program's bridge without Java: answers as the bridge would, and one event."""

    def __init__(self, *, java_dirs: list[Path], desktop: str | None, events: bool) -> None:
        self.java_dirs, self.desktop, self.want_events = java_dirs, desktop, events
        self.ready, self.status, self.stuck = False, "not started", False
        self.dll_path: Path | None = None
        self.queued: list[dict[str, Any]] = [EVENT]
        self.texts: list[tuple[int, str, str, Node | None]] = []

    def start(self, timeout: float = 10.0) -> Program:
        if Path("nothing") in self.java_dirs:  # a computer without the bridge
            raise AccessBridgeError(
                "no WindowsAccessBridge-32.dll or WindowsAccessBridge-64.dll in the Java folders"
            )
        self.ready, self.status = True, "ready"
        self.dll_path = JRE8 / "WindowsAccessBridge-32.dll"
        return self

    def clock(self) -> float:
        return 12.5

    def events(self) -> list[dict[str, Any]]:
        out, self.queued = self.queued, []
        return out

    def close(self) -> None:
        self.ready = False

    def windows(self, *, pid: int | None = None, java_only: bool = True) -> list[Window]:
        return [WINDOW]

    def tree(self, hwnd: int, *, root: str = "0", **_: Any) -> list[Node]:
        return [FIELD] if hwnd == WINDOW.hwnd and root == "0/1" else []

    def focus(self, hwnd: int) -> tuple[Node, list[tuple[str, str]], int]:
        return FIELD, CHAIN, hwnd

    def node(self, hwnd: int, path: str) -> Node | None:
        raise StaleNodeError(f"the element at {path} is gone (window changed)")

    def set_text(self, hwnd: int, path: str, text: str, expect: Node | None = None) -> bool:
        self.texts.append((hwnd, path, text, expect))
        return True

    def table(self, hwnd: int, path: str, *, max_rows: int = 500) -> Table | None:
        return Table(["Indeks"], [["26386"]], [0])

    def do_action(self, hwnd: int, path: str, action: str, expect: Node | None = None) -> bool:
        self.stuck = True  # as the bridge's thread when a modal window keeps the call waiting
        raise AccessBridgeError(
            "the Java program does not answer (a window it opened may be waiting)"
        )


class Pipes:
    """The helper in a thread behind pipes: what RemoteBridge starts as a process."""

    def __init__(self) -> None:
        theirs_in, self._ours_out = os.pipe()
        self._ours_in, theirs_out = os.pipe()
        log_in, log_out = os.pipe()
        self.stdin = os.fdopen(self._ours_out, "wb")
        self.stdout = os.fdopen(self._ours_in, "rb")
        self.stderr = os.fdopen(log_in, "rb")
        self.program: Program | None = None
        source, self.sink = os.fdopen(theirs_in, "rb"), os.fdopen(theirs_out, "wb")
        log = os.fdopen(log_out, "wb")

        def make(**options: Any) -> Program:
            self.program = Program(**options)
            return self.program

        def run() -> None:
            try:
                answer_all(source, self.sink, make=make)
            finally:
                for end in (self.sink, source, log):
                    end.close()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def end(self) -> None:
        """The helper is gone (it crashed): its output closes."""
        self.sink.close()

    def wait(self, timeout: float | None = None) -> int:
        self.thread.join(timeout)
        if self.thread.is_alive():
            raise subprocess.TimeoutExpired("helper", timeout or 0)
        return 0

    def kill(self) -> None:
        self.stdin.close()


class Piped(RemoteBridge):
    pipes: Pipes

    def _spawn(self) -> Any:
        self.pipes = Pipes()
        return self.pipes


def piped(**options: Any) -> Piped:
    return Piped(Path("python32/python.exe"), **options)


def test_the_helper_answers_what_the_bridge_answers() -> None:
    bridge = piped(java_dirs=[JRE8], events=True).start()
    try:
        assert bridge.ready
        assert bridge.dll_path == JRE8 / "WindowsAccessBridge-32.dll"
        assert bridge.windows() == [WINDOW]
        assert bridge.tree(WINDOW.hwnd, root="0/1") == [FIELD]
        assert bridge.focus(WINDOW.hwnd) == (FIELD, CHAIN, WINDOW.hwnd)
        assert bridge.set_text(WINDOW.hwnd, "0/1/2", "K0002", expect=FIELD) is True
        program = bridge.pipes.program
        assert program is not None
        assert program.texts == [(WINDOW.hwnd, "0/1/2", "K0002", FIELD)]
        assert bridge.table(WINDOW.hwnd, "0/4") == Table(["Indeks"], [["26386"]], [0])
        with pytest.raises(StaleNodeError, match="is gone"):
            bridge.node(WINDOW.hwnd, "0/9")
        events: list[dict[str, Any]] = []
        end = time.time() + 5
        while not events and time.time() < end:
            events = bridge.events()
            time.sleep(0.02)
        assert events == [EVENT]
        assert 12.5 <= bridge.clock() < 30  # the helper's clock: the events' times
    finally:
        bridge.close()
    assert not bridge.ready


def test_a_program_that_does_not_answer_stops_the_questions() -> None:
    bridge = piped().start()
    try:
        with pytest.raises(AccessBridgeError, match="does not answer"):
            bridge.do_action(WINDOW.hwnd, "0/1/5", "click")
        assert bridge.stuck
        with pytest.raises(AccessBridgeError, match="still does not answer"):
            bridge.windows()
    finally:
        bridge.close()


def test_a_bridge_that_does_not_start_says_why() -> None:
    bridge = piped(java_dirs=[Path("nothing")])
    with pytest.raises(AccessBridgeError, match=r"no WindowsAccessBridge-32\.dll"):
        bridge.start()
    assert not bridge.ready


def test_a_helper_that_ends_is_noticed() -> None:
    bridge = piped().start()
    bridge.pipes.end()
    end = time.time() + 5
    while bridge.ready and time.time() < end:
        time.sleep(0.02)
    with pytest.raises(AccessBridgeError, match="helper of the Java Access Bridge ended"):
        bridge.windows()
    bridge.close()


def test_every_question_of_the_bridge_goes_to_the_helper() -> None:
    """A question added to Bridge must be added to the helper too, or it would wait in vain
    for a thread this process does not run."""
    public = {name for name, value in vars(Bridge).items() if callable(value) and name[0] != "_"}
    built_on_others = {"text", "events", "clock"}  # node(); events and time read here
    assert sorted(public - built_on_others - set(vars(RemoteBridge))) == []
    assert public - built_on_others - {"start", "close", "call"} == jab_remote.ASKED


def test_a_real_helper_process_starts_and_says_what_its_bridge_says() -> None:
    """The helper as Maptelo starts it: this very Python, from Maptelo's own folder."""
    bridge = RemoteBridge(Path(sys.executable))
    if jab.find_dll() is None:  # no Windows, or no Java: what its bridge says comes back
        with pytest.raises(AccessBridgeError, match=r"Java Access Bridge|WindowsAccessBridge"):
            bridge.start(timeout=5)
        assert not bridge.ready
        return
    bridge.start(timeout=5)
    try:
        assert bridge.dll_path is not None
        assert bridge.dll_path.name == f"WindowsAccessBridge-{jab.python_bits()}.dll"
        assert isinstance(bridge.windows(), list)
    finally:
        bridge.close()


# -- the helper Python ------------------------------------------------------------------------


def test_the_helper_python_is_the_one_named_shipped_or_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shipped = program_file(tmp_path / "python32", "python.exe", X86)
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "python"))
    monkeypatch.delenv("MAPTELO_PYTHON32", raising=False)
    monkeypatch.setattr(jab_remote, "registered_pythons", lambda bits: [])
    assert jab_remote.helper_python(32) == shipped
    named = program_file(tmp_path / "it", "python.exe", X86)
    monkeypatch.setenv("MAPTELO_PYTHON32", str(named))
    assert jab_remote.helper_python(32) == named
    monkeypatch.setenv("MAPTELO_PYTHON32", str(program_file(tmp_path / "x64", "python.exe", X64)))
    assert jab_remote.helper_python(32) == shipped  # named, but of the other bitness
    shipped.unlink()
    installed = program_file(tmp_path / "Python312-32", "python.exe", X86)
    monkeypatch.setattr(jab_remote, "registered_pythons", lambda bits: [installed])
    assert jab_remote.helper_python(32) == installed
    monkeypatch.setattr(jab_remote, "registered_pythons", lambda bits: [])
    assert jab_remote.helper_python(32) is None
