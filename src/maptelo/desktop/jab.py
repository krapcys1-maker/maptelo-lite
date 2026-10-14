"""The Java Access Bridge: how Maptelo sees Java programs and acts in them.

The bridge is a library of the Java runtime (``WindowsAccessBridge-64.dll``, or ``-32`` for a
32-bit Java such as the one Oracle Forms runs on) that answers questions about a Java window's
accessibility tree: every window, frame, field, button and list, with its role, name, state,
place and text. A Java program answers only when the bridge is on for it: switched on for the
user (``jabswitch -enable``, as at a company where IT turned it on) or started with
``-Djavax.accessibility.assistive_technologies=com.sun.java.accessibility.AccessBridge``.
Python loads only a library of its own bitness: where the Java here has only the other one (a
32-bit Java 7 or 8 next to Maptelo Lite's 64-bit Python), ``connect`` starts the bridge in a
helper Python of that bitness (``jab_remote``), which answers the same questions.

All calls go through one thread that also runs the message loop the bridge needs; its events
(focus, clicks, text changes, menus, windows opening) are collected there for the recorder.

Acting stays inside the program: focus is asked for through the bridge, text is set through it,
choices in lists, combo boxes and tabs are made through its selection, and keys are posted to
the program's window (``desktop.keys``). Two of the bridge's own ways are never used for what
may open a modal window: a Swing dialog keeps the call (and the whole bridge) waiting until it
is closed. A button is pressed with the space key once it has the focus, as a person does.
"""

from __future__ import annotations

import ctypes
import os
import queue
import struct
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

J = ctypes.c_int64
"""A Java object reference as the 64-bit (and the newer 32-bit) bridge passes it."""
VM = ctypes.c_long
HWND = ctypes.c_void_p

MAX_TEXT = 30_000
SECRET = "\u2022\u2022\u2022"
"""What a password field shows in Maptelo: never its content."""
SECRET_ROLES = frozenset({"password text"})


class AccessBridgeError(RuntimeError):
    """The bridge cannot be used: not found, not started, or the program does not answer."""


class StaleNodeError(AccessBridgeError):
    """An element changed or went away between seeing it and acting on it."""


@dataclass(frozen=True)
class Node:
    """One element of a Java window, as the bridge describes it."""

    path: str
    """Child indexes from the window's root: ``0/1/0/3``. Valid until the window changes."""
    role: str
    name: str
    description: str = ""
    states: frozenset[str] = frozenset()
    box: tuple[int, int, int, int] = (0, 0, 0, 0)
    children: int = 0
    index: int = -1
    text: str | None = None
    """What a text-like element holds; None when it does not say. A password: ``SECRET``."""
    interfaces: int = 0
    actions: tuple[str, ...] = ()

    @property
    def showing(self) -> bool:
        return "showing" in self.states

    @property
    def enabled(self) -> bool:
        return "enabled" in self.states

    @property
    def focused(self) -> bool:
        return "focused" in self.states

    @property
    def editable(self) -> bool:
        return "editable" in self.states

    @property
    def checked(self) -> bool:
        return "checked" in self.states

    @property
    def selected(self) -> bool:
        return "selected" in self.states

    @property
    def depth(self) -> int:
        return self.path.count("/")

    def is_under(self, other: Node) -> bool:
        return self.path.startswith(other.path + "/")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "role": self.role,
            "name": self.name,
            "description": self.description,
            "states": sorted(self.states),
            "box": list(self.box),
            "children": self.children,
            "index": self.index,
            "text": self.text,
            "actions": list(self.actions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Node:
        box = tuple(data.get("box") or (0, 0, 0, 0))
        return cls(
            path=str(data["path"]),
            role=str(data["role"]),
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            states=frozenset(data.get("states") or ()),
            box=(int(box[0]), int(box[1]), int(box[2]), int(box[3])),
            children=int(data.get("children") or 0),
            index=int(data.get("index", -1)),
            text=data.get("text"),
            actions=tuple(data.get("actions") or ()),
        )


@dataclass(frozen=True)
class Window:
    """A top-level window of the desktop."""

    hwnd: int
    title: str
    pid: int
    java: bool
    owner: int = 0
    box: tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass
class Table:
    """What a table (a Swing JTable) shows: headers, the rows' texts and which are selected."""

    headers: list[str]
    rows: list[list[str]]
    selected: list[int] = field(default_factory=list)


def states_of(text: str) -> frozenset[str]:
    return frozenset(s.strip() for s in text.split(",") if s.strip())


# -- the library ------------------------------------------------------------------------------


def python_bits() -> int:
    return struct.calcsize("P") * 8


def other_bits(bits: int | None = None) -> int:
    return 32 if (bits or python_bits()) == 64 else 64


def pe_bits(path: Path) -> int | None:
    """32 or 64: the bitness of a Windows program or library, read from its PE header (the
    machine it is built for). None: not there, or not an x86 or x64 program."""
    try:
        with path.open("rb") as file:
            head = file.read(64)
            if len(head) < 64 or head[:2] != b"MZ":
                return None
            file.seek(struct.unpack_from("<I", head, 0x3C)[0])
            header = file.read(6)
    except OSError:
        return None
    if len(header) < 6 or header[:4] != b"PE\0\0":
        return None
    return {0x014C: 32, 0x8664: 64}.get(struct.unpack_from("<H", header, 4)[0])


def dll_names(bits: int | None = None) -> list[str]:
    """The bridge library for this Python: a 64-bit Python loads the 64-bit one, a 32-bit
    Python the 32-bit one (the oldest, ``WindowsAccessBridge.dll``, passes objects
    differently and is not used)."""
    if (bits or python_bits()) == 64:
        return ["WindowsAccessBridge-64.dll"]
    return ["WindowsAccessBridge-32.dll"]


def candidate_dirs(extra: list[Path] | None = None, bits: int | None = None) -> list[Path]:
    """Where a Java runtime keeps the bridge: the folders given (the Java program's own, first),
    JAVA_HOME, the Java on PATH, the usual install folders, then Windows' own folder for
    libraries of that bitness (a JRE installer that turned the bridge on copies it there)."""
    dirs: list[Path] = list(extra or [])
    home = os.environ.get("JAVA_HOME")
    if home:
        dirs.append(Path(home) / "bin")
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry and (Path(entry) / "java.exe").exists():
            dirs.append(Path(entry))
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)")):
        if not base:
            continue
        for vendor in ("Java", "Eclipse Adoptium", "Microsoft", "Zulu", "Amazon Corretto"):
            root = Path(base) / vendor
            try:
                for sub in sorted(root.iterdir(), reverse=True):
                    dirs.append(sub / "bin")
                    dirs.append(sub / "jre" / "bin")
            except OSError:
                continue
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    if (bits or python_bits()) == 32:  # a 64-bit program sees the 32-bit ones in SysWOW64
        dirs.append(windir / ("SysWOW64" if python_bits() == 64 else "System32"))
    else:  # and a 32-bit program the 64-bit ones in Sysnative
        dirs.append(windir / ("System32" if python_bits() == 64 else "Sysnative"))
    seen: set[str] = set()
    unique = []
    for d in dirs:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


def find_dlls(extra: list[Path] | None = None, bits: int | None = None) -> list[Path]:
    """Every bridge library of that bitness (this Python's by default), in the order of
    ``candidate_dirs``: a library its header says is of the other bitness is not one."""
    bits = bits or python_bits()
    found = []
    for folder in candidate_dirs(extra, bits):
        for name in dll_names(bits):
            path = folder / name
            if path.exists() and pe_bits(path) in (bits, None):
                found.append(path)
    return found


def find_dll(extra: list[Path] | None = None, bits: int | None = None) -> Path | None:
    found = find_dlls(extra, bits)
    return found[0] if found else None


@dataclass(frozen=True)
class BridgeLibrary:
    """The bridge library this computer's Java has, and the Python that loads it."""

    path: Path
    bits: int
    python: Path | None = None
    """For a library of the other bitness: the helper Python of its bitness that loads it
    (None: there is none here). For one of this Python's bitness: None, this Python loads it."""

    @property
    def usable(self) -> bool:
        return self.bits == python_bits() or self.python is not None


def bridge_library(extra: list[Path] | None = None) -> BridgeLibrary | None:
    """The library the bridge would use here: one of this Python's bitness first, else one
    of the other bitness and the helper Python for it. None: no bridge library at all."""
    own = find_dll(extra)
    if own is not None:
        return BridgeLibrary(own, python_bits())
    found = find_dll(extra, other_bits())
    if found is None:
        return None
    from maptelo.desktop.jab_remote import helper_python  # loaded when asked

    return BridgeLibrary(found, other_bits(), helper_python(other_bits()))


def no_helper(library: BridgeLibrary) -> str:
    """Why a library of the other bitness cannot be used: no Python of its bitness."""
    return (
        f"the Java here has only {library.path.name} ({library.bits}-bit), which this "
        f"{python_bits()}-bit Python cannot load, and no Python of its bitness was found to load "
        "it: install Maptelo again (it brings one along) or Python 3.12 of that bitness for "
        "this user"
    )


def connect(
    *,
    java_dirs: list[Path] | None = None,
    desktop: str | None = None,
    events: bool = False,
    timeout: float = 10.0,
) -> Bridge:
    """A started bridge: in this Python when the Java here has a library of its bitness, else
    in a helper Python of the library's (``jab_remote.RemoteBridge``, the same questions and
    answers). ``java_dirs``: the Java program's own folders, looked in first."""
    library = bridge_library(java_dirs)
    if library is not None and library.bits != python_bits():
        if library.python is None:
            raise AccessBridgeError(no_helper(library))
        from maptelo.desktop.jab_remote import RemoteBridge

        remote = RemoteBridge(library.python, java_dirs=java_dirs, desktop=desktop, events=events)
        return remote.start(timeout)
    return Bridge(java_dirs=java_dirs, desktop=desktop, events=events).start(timeout)


class _ACInfo(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_wchar * 1024),
        ("description", ctypes.c_wchar * 1024),
        ("role", ctypes.c_wchar * 256),
        ("role_en_US", ctypes.c_wchar * 256),
        ("states", ctypes.c_wchar * 256),
        ("states_en_US", ctypes.c_wchar * 256),
        ("indexInParent", ctypes.c_int),
        ("childrenCount", ctypes.c_int),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("accessibleComponent", ctypes.c_int),
        ("accessibleAction", ctypes.c_int),
        ("accessibleSelection", ctypes.c_int),
        ("accessibleText", ctypes.c_int),
        ("accessibleInterfaces", ctypes.c_int),
        ("_spare", ctypes.c_byte * 512),
    ]


class _ATInfo(ctypes.Structure):
    _fields_ = [
        ("charCount", ctypes.c_int),
        ("caretIndex", ctypes.c_int),
        ("indexAtPoint", ctypes.c_int),
    ]


class _ActionInfo(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar * 256)]


class _Actions(ctypes.Structure):
    _fields_ = [("actionsCount", ctypes.c_int), ("actionInfo", _ActionInfo * 256)]


class _ActionsToDo(ctypes.Structure):
    _fields_ = [("actionsCount", ctypes.c_int), ("actions", _ActionInfo * 32)]


class _TableInfo(ctypes.Structure):
    _fields_ = [
        ("caption", J),
        ("summary", J),
        ("rowCount", ctypes.c_int),
        ("columnCount", ctypes.c_int),
        ("accessibleContext", J),
        ("accessibleTable", J),
    ]


class _TableCellInfo(ctypes.Structure):
    _fields_ = [
        ("accessibleContext", J),
        ("index", ctypes.c_int),
        ("row", ctypes.c_int),
        ("column", ctypes.c_int),
        ("rowExtent", ctypes.c_int),
        ("columnExtent", ctypes.c_int),
        ("isSelected", ctypes.c_int),
    ]


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _Msg(ctypes.Structure):
    _fields_ = [
        ("hwnd", HWND),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_ulong),
        ("pt", _Point),
        ("lPrivate", ctypes.c_ulong),
    ]


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _winapi(name: str) -> Any:
    """A Windows library, typed loosely: the module also imports where there is none."""
    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        raise AccessBridgeError("the Java Access Bridge works on Windows only")
    return loader(name, use_last_error=True)


def _sig(fn: Any, res: Any, args: list[Any]) -> None:
    fn.restype, fn.argtypes = res, args


JAVA_FRAMES = ("SunAwtFrame", "SunAwtDialog", "GlassWndClass")
"""The window classes of Java's own windows: AWT and Swing (Oracle Forms too), JavaFX."""


def java_frames() -> list[Window]:
    """The main windows of the Java programs open on this desktop, front first: told by their
    window class, without the bridge, so a program the bridge is off for is listed too (and
    recording it then says the bridge is off). Empty where there is no Windows."""
    if sys.platform != "win32":
        return []
    u = _winapi("user32")
    enum_proc = getattr(ctypes, "WINFUNCTYPE")(ctypes.c_int, HWND, ctypes.c_ssize_t)  # noqa: B009
    _sig(u.EnumWindows, ctypes.c_int, [enum_proc, ctypes.c_ssize_t])
    _sig(u.IsWindowVisible, ctypes.c_int, [HWND])
    _sig(u.GetWindow, HWND, [HWND, ctypes.c_uint])
    _sig(u.GetClassNameW, ctypes.c_int, [HWND, ctypes.c_wchar_p, ctypes.c_int])
    _sig(u.GetWindowTextLengthW, ctypes.c_int, [HWND])
    _sig(u.GetWindowTextW, ctypes.c_int, [HWND, ctypes.c_wchar_p, ctypes.c_int])
    _sig(u.GetWindowThreadProcessId, ctypes.c_ulong, [HWND, ctypes.POINTER(ctypes.c_ulong)])
    _sig(u.GetWindowRect, ctypes.c_int, [HWND, ctypes.POINTER(_Rect)])
    found: list[Window] = []

    def visit(handle: int, _: int) -> int:
        if not handle or not u.IsWindowVisible(handle) or u.GetWindow(handle, 4):  # GW_OWNER
            return 1  # hidden, or a dialog of another window
        kind = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(handle, kind, 256)
        length = u.GetWindowTextLengthW(handle)
        if not kind.value.startswith(JAVA_FRAMES) or length <= 0:
            return 1
        title = ctypes.create_unicode_buffer(length + 1)
        u.GetWindowTextW(handle, title, length + 1)
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        rect = _Rect()
        u.GetWindowRect(handle, ctypes.byref(rect))
        box = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
        found.append(Window(int(handle), title.value, int(pid.value), True, 0, box))
        return 1

    u.EnumWindows(enum_proc(visit), 0)
    return found


def program_folder(pid: int) -> Path | None:
    """The folder of a running program's executable: for a Java program, the bin folder of
    its own Java, where its bridge library is. None when Windows does not say."""
    if sys.platform != "win32":
        return None
    k = _winapi("kernel32")
    _sig(k.OpenProcess, HWND, [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong])
    _sig(
        k.QueryFullProcessImageNameW,
        ctypes.c_int,
        [HWND, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)],
    )
    _sig(k.CloseHandle, ctypes.c_int, [HWND])
    handle = k.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        size = ctypes.c_ulong(1024)
        path = ctypes.create_unicode_buffer(size.value)
        if not k.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            return None
        return Path(path.value).parent
    finally:
        k.CloseHandle(handle)


# Event callbacks as the bridge declares them.
_EV = ctypes.CFUNCTYPE(None, VM, J, J)
_EV_STR2 = ctypes.CFUNCTYPE(None, VM, J, J, ctypes.c_wchar_p, ctypes.c_wchar_p)
_EV_OBJ2 = ctypes.CFUNCTYPE(None, VM, J, J, J, J)
_EV_INT2 = ctypes.CFUNCTYPE(None, VM, J, J, ctypes.c_int, ctypes.c_int)
_EV_PROP = ctypes.CFUNCTYPE(None, VM, J, J, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p)

EVENT_KINDS = (
    "focus",
    "mouse_clicked",
    "mouse_pressed",
    "menu_selected",
    "popup_visible",
    "text_changed",
    "selection_changed",
    "visible_data_changed",
    "state_changed",
    "value_changed",
    "name_changed",
    "child_changed",
    "active_descendant",
)


class Bridge:
    """One connection to the Java Access Bridge, on its own thread.

    ``desktop``: the name of a Windows desktop to work on (Wiórek's desktop in the benchmark);
    by default the one Maptelo runs on. ``events``: collect the bridge's events (recording).
    """

    def __init__(
        self,
        *,
        dll: Path | None = None,
        java_dirs: list[Path] | None = None,
        desktop: str | None = None,
        events: bool = False,
    ) -> None:
        self.dll_path = dll
        self.java_dirs = java_dirs or []
        self.desktop = desktop
        self.want_events = events
        self.status = "not started"
        self.ready = False
        self._d: Any = None
        self._user32: Any = None
        self._tasks: queue.Queue[tuple[Callable[[], Any], dict[str, Any], threading.Event]] = (
            queue.Queue()
        )
        self._events: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stop = threading.Event()
        self._started = threading.Event()
        self._thread: threading.Thread | None = None
        self._callbacks: list[Any] = []
        self._t0 = time.time()

    # -- life ------------------------------------------------------------------------------

    def start(self, timeout: float = 10.0) -> Bridge:
        if self._thread is not None:
            return self
        self.stuck = False
        self._thread = threading.Thread(target=self._run, name="java-access-bridge", daemon=True)
        self._thread.start()
        if not self._started.wait(timeout):
            raise AccessBridgeError(f"the Java Access Bridge did not start ({self.status})")
        if not self.ready:
            raise AccessBridgeError(self.status)
        return self

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> Bridge:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _run(self) -> None:
        try:
            self._user32 = _winapi("user32")
            self._prepare_user32()
            if self.desktop:
                self._attach_desktop(self.desktop)
            paths = [self.dll_path] if self.dll_path else find_dlls(self.java_dirs)
            if not paths:
                self.status = (
                    f"no {dll_names()[0]} or {dll_names(other_bits())[0]} in the Java folders"
                )
                self._started.set()
                return
            self._d = self._load(paths)
            self._prototypes()
            if self.want_events:
                self._subscribe()
            self._d.Windows_run()
        except (OSError, AttributeError, AccessBridgeError) as exc:
            self.status = f"the Java Access Bridge could not start: {exc}"
            self._started.set()
            return
        msg = _Msg()
        started = time.time()
        while not self._stop.is_set():
            self._user32.MsgWaitForMultipleObjects(0, None, 0, 10, 0x04FF)
            while self._user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                self._user32.TranslateMessage(ctypes.byref(msg))
                self._user32.DispatchMessageW(ctypes.byref(msg))
            if not self._started.is_set() and time.time() - started > 1.0:
                # the bridge finds the Java programs in the first second of its message loop
                self.ready = True
                self.status = "ready"
                self._started.set()
            while True:
                try:
                    task, box, done = self._tasks.get_nowait()
                except queue.Empty:
                    break
                try:
                    box["result"] = task()
                except BaseException as exc:
                    box["error"] = exc
                done.set()

    def _load(self, paths: list[Path]) -> Any:
        """The first of the libraries that loads: one may lack what it needs beside it (a copy
        in Windows' folder without its Java's runtime library), another Java's then serves."""
        failed = []
        for path in paths:
            try:
                library = ctypes.CDLL(str(path))
            except OSError as exc:
                failed.append(f"{path}: {exc}")
                continue
            self.dll_path = path
            return library
        raise AccessBridgeError("; ".join(failed))

    def _attach_desktop(self, name: str) -> None:
        handle = self._user32.OpenDesktopW(name, 0, False, 0x10000000)
        if not handle or not self._user32.SetThreadDesktop(handle):
            raise AccessBridgeError(f"cannot work on the desktop {name!r}")

    def call(self, task: Callable[[], T], timeout: float = 30.0) -> T:
        """Run ``task`` on the bridge's thread and return what it returned."""
        if threading.current_thread() is self._thread:
            return task()
        if not self.ready:
            raise AccessBridgeError(self.status)
        if self.stuck:
            raise AccessBridgeError(
                "the Java program still does not answer (a window it opened may be waiting)"
            )
        box: dict[str, Any] = {}
        done = threading.Event()
        self._tasks.put((task, box, done))
        if not done.wait(timeout):
            self.stuck = True  # the bridge's thread waits for the program: nothing else passes
            raise AccessBridgeError(
                "the Java program does not answer (a window it opened may be waiting)"
            )
        if "error" in box:
            raise box["error"]
        result: T = box["result"]
        return result

    # -- prototypes ------------------------------------------------------------------------

    def _prepare_user32(self) -> None:
        u = self._user32
        _sig(
            u.MsgWaitForMultipleObjects,
            ctypes.c_ulong,
            [ctypes.c_ulong, ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong],
        )
        _sig(
            u.PeekMessageW,
            ctypes.c_int,
            [ctypes.POINTER(_Msg), HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint],
        )
        _sig(u.TranslateMessage, ctypes.c_int, [ctypes.POINTER(_Msg)])
        _sig(u.DispatchMessageW, ctypes.c_ssize_t, [ctypes.POINTER(_Msg)])
        _sig(
            u.OpenDesktopW,
            ctypes.c_void_p,
            [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong],
        )
        _sig(u.SetThreadDesktop, ctypes.c_int, [ctypes.c_void_p])
        _sig(u.GetWindowTextW, ctypes.c_int, [HWND, ctypes.c_wchar_p, ctypes.c_int])
        _sig(u.GetWindowTextLengthW, ctypes.c_int, [HWND])
        _sig(u.IsWindowVisible, ctypes.c_int, [HWND])
        _sig(u.GetWindowThreadProcessId, ctypes.c_ulong, [HWND, ctypes.POINTER(ctypes.c_ulong)])
        _sig(u.GetWindow, HWND, [HWND, ctypes.c_uint])
        _sig(u.GetWindowRect, ctypes.c_int, [HWND, ctypes.POINTER(_Rect)])
        _sig(u.GetAncestor, HWND, [HWND, ctypes.c_uint])

    def _prototypes(self) -> None:
        d = self._d
        _sig(d.Windows_run, None, [])
        _sig(d.isJavaWindow, ctypes.c_int, [HWND])
        for fn in (d.getAccessibleContextFromHWND, d.getAccessibleContextWithFocus):
            _sig(fn, ctypes.c_int, [HWND, ctypes.POINTER(VM), ctypes.POINTER(J)])
        _sig(d.getAccessibleContextInfo, ctypes.c_int, [VM, J, ctypes.POINTER(_ACInfo)])
        _sig(d.getAccessibleChildFromContext, J, [VM, J, ctypes.c_int])
        _sig(d.getAccessibleParentFromContext, J, [VM, J])
        _sig(d.getTopLevelObject, J, [VM, J])
        _sig(d.getHWNDFromAccessibleContext, HWND, [VM, J])
        _sig(d.releaseJavaObject, None, [VM, J])
        _sig(
            d.getAccessibleTextInfo,
            ctypes.c_int,
            [VM, J, ctypes.POINTER(_ATInfo), ctypes.c_int, ctypes.c_int],
        )
        _sig(
            d.getAccessibleTextRange,
            ctypes.c_int,
            [VM, J, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p, ctypes.c_short],
        )
        _sig(d.getAccessibleActions, ctypes.c_int, [VM, J, ctypes.POINTER(_Actions)])
        _sig(
            d.doAccessibleActions,
            ctypes.c_int,
            [VM, J, ctypes.POINTER(_ActionsToDo), ctypes.POINTER(ctypes.c_int)],
        )
        _sig(d.setTextContents, ctypes.c_int, [VM, J, ctypes.c_wchar_p])
        _sig(d.requestFocus, ctypes.c_int, [VM, J])
        _sig(d.addAccessibleSelectionFromContext, None, [VM, J, ctypes.c_int])
        _sig(d.clearAccessibleSelectionFromContext, None, [VM, J])
        _sig(d.isAccessibleChildSelectedFromContext, ctypes.c_int, [VM, J, ctypes.c_int])
        _sig(d.getAccessibleTableInfo, ctypes.c_int, [VM, J, ctypes.POINTER(_TableInfo)])
        _sig(d.getAccessibleTableColumnHeader, ctypes.c_int, [VM, J, ctypes.POINTER(_TableInfo)])
        _sig(
            d.getAccessibleTableCellInfo,
            ctypes.c_int,
            [VM, J, ctypes.c_int, ctypes.c_int, ctypes.POINTER(_TableCellInfo)],
        )
        _sig(d.selectTextRange, ctypes.c_int, [VM, J, ctypes.c_int, ctypes.c_int])
        _sig(d.isSameObject, ctypes.c_int, [VM, J, J])

    # -- low level (bridge thread only) ------------------------------------------------------

    def _release(self, vm: int, *objs: int) -> None:
        for obj in objs:
            if obj:
                self._d.releaseJavaObject(vm, obj)

    def _info(self, vm: int, obj: int) -> _ACInfo | None:
        info = _ACInfo()
        if not obj or not self._d.getAccessibleContextInfo(vm, obj, ctypes.byref(info)):
            return None
        return info

    def _read_text(self, vm: int, obj: int) -> str | None:
        ti = _ATInfo()
        if not self._d.getAccessibleTextInfo(vm, obj, ctypes.byref(ti), 0, 0):
            return None
        n = max(0, min(ti.charCount, MAX_TEXT))
        if n == 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 2)
        if not self._d.getAccessibleTextRange(vm, obj, 0, n - 1, buf, n + 1):
            return None
        return buf.value

    def _actions(self, vm: int, obj: int) -> tuple[str, ...]:
        found = _Actions()
        if not self._d.getAccessibleActions(vm, obj, ctypes.byref(found)):
            return ()
        return tuple(found.actionInfo[i].name for i in range(min(found.actionsCount, 256)))

    def _node(self, vm: int, obj: int, path: str, *, text: bool = True) -> Node | None:
        info = self._info(vm, obj)
        if info is None:
            return None
        role = info.role_en_US or info.role
        value: str | None = None
        if info.accessibleText and text:
            value = SECRET if role in SECRET_ROLES else self._read_text(vm, obj)
        return Node(
            path=path,
            role=role,
            name=info.name,
            description=info.description,
            states=states_of(info.states_en_US or info.states),
            box=(info.x, info.y, info.width, info.height),
            children=info.childrenCount,
            index=info.indexInParent,
            text=value,
            interfaces=info.accessibleInterfaces,
            actions=self._actions(vm, obj) if info.accessibleAction else (),
        )

    def _root(self, hwnd: int) -> tuple[int, int]:
        vm, ac = VM(), J()
        if not self._d.getAccessibleContextFromHWND(hwnd, ctypes.byref(vm), ctypes.byref(ac)):
            raise AccessBridgeError(f"window {hwnd:#x} does not answer through the bridge")
        if not ac.value:
            raise AccessBridgeError(f"window {hwnd:#x} has no accessible root")
        return int(vm.value), int(ac.value)

    def _resolve(self, hwnd: int, path: str) -> tuple[int, int, list[int]]:
        """The element at ``path``: (vm, object, objects to release)."""
        vm, root = self._root(hwnd)
        owned = [root]
        current = root
        for part in path.split("/")[1:]:
            child = self._d.getAccessibleChildFromContext(vm, current, int(part))
            if not child:
                self._release(vm, *owned)
                raise StaleNodeError(f"the element at {path} is gone (window changed)")
            owned.append(child)
            current = child
        return vm, current, owned

    def _with(self, hwnd: int, path: str, expect: Node | None, act: Callable[[int, int], T]) -> T:
        vm, obj, owned = self._resolve(hwnd, path)
        try:
            if expect is not None:
                now = self._node(vm, obj, path, text=False)
                if now is None or now.role != expect.role or now.name != expect.name:
                    seen = f"{now.role} {now.name!r}" if now else "nothing"
                    raise StaleNodeError(
                        f"{expect.role} {expect.name!r} is no longer there ({seen} instead)"
                    )
            return act(vm, obj)
        finally:
            self._release(vm, *owned)

    def _path_of(self, vm: int, obj: int) -> tuple[str, int]:
        """The element's path from its window's root, and that window (0 when the bridge
        cannot tell it)."""
        indexes: list[int] = []
        owned: list[int] = []
        current = obj
        hwnd = 0
        try:
            for _ in range(80):
                # the window it is in: a dialog's parent is the window that owns it, so the
                # climb stops at the first top-level window met
                handle = int(self._d.getHWNDFromAccessibleContext(vm, current) or 0)
                if handle and self._top_level(handle):
                    hwnd = handle
                    break
                info = self._info(vm, current)
                parent = self._d.getAccessibleParentFromContext(vm, current)
                if not parent or info is None:
                    break
                owned.append(parent)
                index = info.indexInParent
                if index < 0:  # a root pane says -1: find it among its parent's children
                    index = self._index_among(vm, parent, current)
                indexes.append(index)
                current = parent
        finally:
            self._release(vm, *owned)
        return "/".join(["0", *(str(i) for i in reversed(indexes))]), hwnd

    def _top_level(self, handle: int) -> bool:
        return int(self._user32.GetAncestor(handle, 2) or 0) == handle  # GA_ROOT

    def _index_among(self, vm: int, parent: int, child: int) -> int:
        info = self._info(vm, parent)
        for i in range(min(info.childrenCount if info else 0, 200)):
            other = self._d.getAccessibleChildFromContext(vm, parent, i)
            if not other:
                continue
            try:
                if self._d.isSameObject(vm, other, child):
                    return i
            finally:
                self._release(vm, other)
        return 0

    def _chain(self, vm: int, obj: int) -> list[tuple[str, str]]:
        """(role, name) of the element's windows, frames and dialogs, innermost first."""
        chain: list[tuple[str, str]] = []
        owned: list[int] = []
        current = obj
        try:
            for _ in range(80):
                parent = self._d.getAccessibleParentFromContext(vm, current)
                if not parent:
                    break
                owned.append(parent)
                info = self._info(vm, parent)
                if info is None:
                    break
                role = info.role_en_US or info.role
                if role in ("internal frame", "dialog", "frame", "window", "alert", "option pane"):
                    chain.append((role, info.name))
                current = parent
        finally:
            self._release(vm, *owned)
        return chain

    # -- windows -----------------------------------------------------------------------------

    def _windows(self, pid: int | None, java_only: bool) -> list[Window]:
        found: list[Window] = []
        u = self._user32
        enum_proc = getattr(ctypes, "WINFUNCTYPE")(ctypes.c_int, HWND, ctypes.c_ssize_t)  # noqa: B009

        def visit(handle: int, _: int) -> int:
            if not handle or not u.IsWindowVisible(handle):
                return 1
            owner_pid = ctypes.c_ulong()
            u.GetWindowThreadProcessId(handle, ctypes.byref(owner_pid))
            if pid is not None and owner_pid.value != pid:
                return 1
            java = bool(self._d.isJavaWindow(handle)) if self._d else False
            if java_only and not java:
                return 1
            length = u.GetWindowTextLengthW(handle)
            buf = ctypes.create_unicode_buffer(max(1, length + 1))
            u.GetWindowTextW(handle, buf, length + 1)
            rect = _Rect()
            u.GetWindowRect(handle, ctypes.byref(rect))
            owner = int(u.GetWindow(handle, 4) or 0)  # GW_OWNER
            found.append(
                Window(
                    int(handle),
                    buf.value,
                    int(owner_pid.value),
                    java,
                    owner,
                    (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
                )
            )
            return 1

        callback = enum_proc(visit)
        _sig(u.EnumWindows, ctypes.c_int, [enum_proc, ctypes.c_ssize_t])
        u.EnumWindows(callback, 0)
        return found

    def windows(self, *, pid: int | None = None, java_only: bool = True) -> list[Window]:
        """Visible top-level windows, front first (Windows' own order)."""
        return self.call(lambda: self._windows(pid, java_only))

    # -- seeing ------------------------------------------------------------------------------

    def tree(
        self,
        hwnd: int,
        *,
        limit: int = 8000,
        showing_only: bool = True,
        texts: bool = True,
        prune: Callable[[Node], bool] | None = None,
        root: str = "0",
    ) -> list[Node]:
        """The window's elements in reading order (depth first). Hidden branches are skipped
        unless ``showing_only`` is off; ``prune`` stops descending below an element; ``root``:
        only the elements under that path (a menu bar's)."""

        def walk() -> list[Node]:
            nodes: list[Node] = []
            if root != "0":
                vm, start, owned = self._resolve(hwnd, root)
                try:
                    visit_from(vm, start, nodes)
                finally:
                    self._release(vm, *owned)
                return nodes
            vm, top = self._root(hwnd)
            try:
                visit_from(vm, top, nodes)
            finally:
                self._release(vm, top)
            return nodes

        def visit_from(vm: int, start: int, nodes: list[Node]) -> None:

            def visit(obj: int, path: str, depth: int) -> None:
                if len(nodes) >= limit:
                    return
                node = self._node(vm, obj, path, text=texts)
                if node is None:
                    return
                if showing_only and not node.showing and depth > 0:
                    return
                nodes.append(node)
                if depth >= 60 or (prune is not None and prune(node)):
                    return
                for i in range(min(node.children, 1000)):
                    child = self._d.getAccessibleChildFromContext(vm, obj, i)
                    if not child:
                        continue
                    try:
                        visit(child, f"{path}/{i}", depth + 1)
                    finally:
                        self._release(vm, child)

            visit(start, root, 0)

        return self.call(walk, timeout=60)

    def focus(self, hwnd: int) -> tuple[Node, list[tuple[str, str]], int] | None:
        """The element with the keyboard focus in the window (its path, the frames and
        dialogs it is in, innermost first, and its top-level window), or None."""

        def find() -> tuple[Node, list[tuple[str, str]], int] | None:
            vm, ac = VM(), J()
            if not self._d.getAccessibleContextWithFocus(hwnd, ctypes.byref(vm), ctypes.byref(ac)):
                return None
            if not ac.value:
                return None
            try:
                path, top = self._path_of(vm.value, ac.value)
                node = self._node(vm.value, ac.value, path)
                if node is None:
                    return None
                return node, self._chain(vm.value, ac.value), top or hwnd
            finally:
                self._release(vm.value, ac.value)

        return self.call(find)

    def has_focus(self, hwnd: int, path: str) -> bool:
        """Whether the element at ``path`` is the one with the keyboard focus (the same Java
        object, not one that looks alike)."""

        def check() -> bool:
            vm, ac = VM(), J()
            if not self._d.getAccessibleContextWithFocus(hwnd, ctypes.byref(vm), ctypes.byref(ac)):
                return False
            if not ac.value:
                return False
            try:
                _, obj, owned = self._resolve(hwnd, path)
            except StaleNodeError:
                self._release(vm.value, ac.value)
                return False
            try:
                return bool(self._d.isSameObject(vm.value, ac.value, obj))
            finally:
                self._release(vm.value, ac.value, *owned)

        return self.call(check)

    def node(self, hwnd: int, path: str) -> Node | None:
        def read() -> Node | None:
            try:
                vm, obj, owned = self._resolve(hwnd, path)
            except StaleNodeError:
                return None
            try:
                return self._node(vm, obj, path)
            finally:
                self._release(vm, *owned)

        return self.call(read)

    def text(self, hwnd: int, path: str) -> str | None:
        node = self.node(hwnd, path)
        return node.text if node else None

    def children_selected(self, hwnd: int, path: str, count: int) -> list[int]:
        def read(vm: int, obj: int) -> list[int]:
            return [
                i
                for i in range(min(count, 2000))
                if self._d.isAccessibleChildSelectedFromContext(vm, obj, i)
            ]

        return self.call(lambda: self._with(hwnd, path, None, read))

    def table(self, hwnd: int, path: str, *, max_rows: int = 500) -> Table | None:
        """A Swing table's headers and rows (as the bridge gives cells: their names)."""

        def read(vm: int, obj: int) -> Table | None:
            info = _TableInfo()
            if not self._d.getAccessibleTableInfo(vm, obj, ctypes.byref(info)):
                return None
            owned = [info.caption, info.summary, info.accessibleContext]
            try:
                headers = self._header(vm, obj, info.columnCount)
                rows: list[list[str]] = []
                selected: list[int] = []
                for r in range(min(info.rowCount, max_rows)):
                    row = []
                    picked = False
                    for c in range(info.columnCount):
                        cell = _TableCellInfo()
                        if not self._d.getAccessibleTableCellInfo(
                            vm, info.accessibleTable, r, c, ctypes.byref(cell)
                        ):
                            row.append("")
                            continue
                        cinfo = self._info(vm, cell.accessibleContext)
                        row.append(cinfo.name if cinfo else "")
                        picked = picked or bool(cell.isSelected)
                        self._release(vm, cell.accessibleContext)
                    rows.append(row)
                    if picked:
                        selected.append(r)
                return Table(headers, rows, selected)
            finally:
                self._release(vm, *(o for o in owned if o))

        return self.call(lambda: self._with(hwnd, path, None, read), timeout=60)

    def table_cell(self, hwnd: int, path: str, row: int, column: int) -> Node | None:
        """Read the actual cell, including checkbox state and screen bounds."""

        def read(vm: int, obj: int) -> Node | None:
            info = _TableInfo()
            if not self._d.getAccessibleTableInfo(vm, obj, ctypes.byref(info)):
                return None
            cell = _TableCellInfo()
            try:
                if not self._d.getAccessibleTableCellInfo(
                    vm, info.accessibleTable, row, column, ctypes.byref(cell)
                ):
                    return None
                return self._node(vm, cell.accessibleContext, path, text=False)
            finally:
                self._release(
                    vm,
                    *(
                        o
                        for o in (
                            cell.accessibleContext,
                            info.caption,
                            info.summary,
                            info.accessibleContext,
                        )
                        if o
                    ),
                )

        return self.call(lambda: self._with(hwnd, path, None, read))

    def _header(self, vm: int, obj: int, columns: int) -> list[str]:
        head = _TableInfo()
        names = [f"#{c + 1}" for c in range(columns)]
        if not self._d.getAccessibleTableColumnHeader(vm, obj, ctypes.byref(head)):
            return names
        try:
            for c in range(min(columns, head.columnCount or columns)):
                cell = _TableCellInfo()
                if self._d.getAccessibleTableCellInfo(
                    vm, head.accessibleTable, 0, c, ctypes.byref(cell)
                ):
                    info = self._info(vm, cell.accessibleContext)
                    if info and info.name:
                        names[c] = info.name
                    self._release(vm, cell.accessibleContext)
        finally:
            self._release(vm, head.caption, head.summary, head.accessibleContext)
        return names

    # -- acting --------------------------------------------------------------------------------

    def request_focus(self, hwnd: int, path: str, expect: Node | None = None) -> bool:
        return self.call(
            lambda: self._with(hwnd, path, expect, lambda vm, o: bool(self._d.requestFocus(vm, o)))
        )

    def set_text(self, hwnd: int, path: str, text: str, expect: Node | None = None) -> bool:
        return self.call(
            lambda: self._with(
                hwnd, path, expect, lambda vm, o: bool(self._d.setTextContents(vm, o, text))
            )
        )

    def select_all_text(self, hwnd: int, path: str, expect: Node | None = None) -> bool:
        def act(vm: int, obj: int) -> bool:
            n = self._read_text(vm, obj)
            return bool(self._d.selectTextRange(vm, obj, 0, len(n or "")))

        return self.call(lambda: self._with(hwnd, path, expect, act))

    def select(
        self, hwnd: int, path: str, index: int, expect: Node | None = None, *, clear: bool = True
    ) -> None:
        """Choose the index-th child of a list, combo box or tab list (only it). ``clear``:
        unselect the others first (a combo box holds one: clearing it would tell the program
        there is no choice, for a moment)."""

        def act(vm: int, obj: int) -> None:
            if clear:
                self._d.clearAccessibleSelectionFromContext(vm, obj)
            self._d.addAccessibleSelectionFromContext(vm, obj, index)

        self.call(lambda: self._with(hwnd, path, expect, act))

    def clear_selection(self, hwnd: int, path: str, expect: Node | None = None) -> None:
        """Nothing chosen in the list or table (a click must then choose a row itself)."""

        def act(vm: int, obj: int) -> None:
            self._d.clearAccessibleSelectionFromContext(vm, obj)

        self.call(lambda: self._with(hwnd, path, expect, act))

    def do_action(self, hwnd: int, path: str, action: str, expect: Node | None = None) -> bool:
        """The element's own action (``click``, ``toggle``...). Only for what opens no modal
        window (a menu of the menu bar): a modal Swing dialog keeps the bridge waiting."""

        def act(vm: int, obj: int) -> bool:
            todo = _ActionsToDo()
            todo.actionsCount = 1
            todo.actions[0].name = action
            failure = ctypes.c_int(-1)
            return bool(
                self._d.doAccessibleActions(vm, obj, ctypes.byref(todo), ctypes.byref(failure))
            )

        return self.call(lambda: self._with(hwnd, path, expect, act), timeout=10)

    # -- events --------------------------------------------------------------------------------

    def _subscribe(self) -> None:
        d = self._d

        def describe(vm: int, src: int, *, text: bool = True) -> dict[str, Any] | None:
            path, top = self._path_of(vm, src)
            node = self._node(vm, src, path, text=text)
            if node is None:
                return None
            return {"node": node.to_dict(), "chain": self._chain(vm, src), "window": top}

        def plain(kind: str, *, text: bool = True) -> Any:
            def handler(vm: int, event: int, src: int) -> None:
                try:
                    self._emit(kind, describe(vm, src, text=text))
                finally:
                    self._release(vm, event, src)

            return _EV(handler)

        def two_strings(kind: str) -> Any:
            def handler(vm: int, event: int, src: int, old: str | None, new: str | None) -> None:
                try:
                    self._emit(kind, describe(vm, src), old=old, new=new)
                finally:
                    self._release(vm, event, src)

            return _EV_STR2(handler)

        def two_objects(kind: str) -> Any:
            def handler(vm: int, event: int, src: int, old: int, new: int) -> None:
                try:
                    self._emit(
                        kind,
                        describe(vm, src, text=False),
                        old=self._brief(vm, old),
                        new=self._brief(vm, new),
                    )
                finally:
                    self._release(vm, event, src, old, new)

            return _EV_OBJ2(handler)

        def caret(vm: int, event: int, src: int, old: int, new: int) -> None:
            self._release(vm, event, src)

        def visible_data(vm: int, event: int, src: int) -> None:
            try:  # often and for every list and table: only what changed, without its text
                info = self._info(vm, src)
                if info is not None:
                    self._emit(
                        "visible_data_changed",
                        {"node": {"role": info.role_en_US or info.role, "name": info.name}},
                    )
            finally:
                self._release(vm, event, src)

        handlers = {
            "setFocusGainedFP": plain("focus"),
            "setMouseClickedFP": plain("mouse_clicked"),
            "setMousePressedFP": plain("mouse_pressed"),
            "setMenuSelectedFP": plain("menu_selected", text=False),
            "setPopupMenuWillBecomeVisibleFP": plain("popup_visible", text=False),
            "setPropertyTextChangeFP": plain("text_changed"),
            "setPropertySelectionChangeFP": plain("selection_changed", text=False),
            "setPropertyVisibleDataChangeFP": _EV(visible_data),
            "setPropertyStateChangeFP": two_strings("state_changed"),
            "setPropertyValueChangeFP": two_strings("value_changed"),
            "setPropertyNameChangeFP": two_strings("name_changed"),
            "setPropertyChildChangeFP": two_objects("child_changed"),
            "setPropertyActiveDescendentChangeFP": two_objects("active_descendant"),
            "setPropertyCaretChangeFP": _EV_INT2(caret),
        }
        for setter, handler in handlers.items():
            fn = getattr(d, setter, None)
            if fn is None:
                continue
            _sig(fn, None, [type(handler)])
            fn(handler)
            self._callbacks.append(handler)

    def _brief(self, vm: int, obj: int) -> dict[str, Any] | None:
        info = self._info(vm, obj) if obj else None
        if info is None:
            return None
        return {
            "role": info.role_en_US or info.role,
            "name": info.name,
            "index": info.indexInParent,
            "states": sorted(states_of(info.states_en_US or info.states)),
        }

    def _emit(self, kind: str, source: dict[str, Any] | None, **extra: Any) -> None:
        self._events.put(
            {"kind": kind, "t": round(time.time() - self._t0, 3), "source": source, **extra}
        )

    def events(self) -> list[dict[str, Any]]:
        """The events collected since the last call, oldest first."""
        out: list[dict[str, Any]] = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    def clock(self) -> float:
        """Seconds since the bridge was made: the time events are stamped with."""
        return round(time.time() - self._t0, 3)


def walk_children(nodes: list[Node], parent: Node) -> Iterator[Node]:
    """The parent's direct children among ``nodes``."""
    depth = parent.depth + 1
    for node in nodes:
        if node.depth == depth and node.is_under(parent):
            yield node


def is_windows() -> bool:
    return sys.platform == "win32"
