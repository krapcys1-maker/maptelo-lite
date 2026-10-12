"""Studio in a window of its own: the company's Edge (or Chrome) in app mode, a window with
no tabs and no address bar, on its own browser profile so it never mixes with the person's
browsing. When neither can start, the default browser opens the page instead.

Nothing beyond what Windows already has (Edge is part of Windows 10 and 11), so it works on
an open laptop and on a locked-down company computer alike (docs/08-srodowiska.md). App mode
needs no remote debugging, so the policies that stop Playwright from driving a browser do
not stop this window.

Whether the window is still open is told by its profile, not by the process Studio started:
Edge started from Program Files hands the window to another process and ends at once, but
any browser holds its profile's ``lockfile`` until its last window is closed.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

from maptelo.environment import Machine, browsers

PROFILE = Path.home() / ".maptelo" / "studio-window"
"""The window's own browser profile: nothing of the person's browsing in it, nor of it there."""
SIZE = (1360, 900)
APPEARS_S = 20.0
"""How long a browser may take to open the window before Studio stops waiting for it."""


TITLE = "Maptelo Studio"
"""The window's title: the page's own, in app mode with nothing added."""
TITLES = (TITLE, "Maptelo Lite")
"""Studio's page as Maptelo and as Maptelo Lite names itself."""
BROWSER_CLASS = "Chrome_WidgetWin_1"
"""The window class of Edge and Chrome, their app windows too."""
SW_MINIMIZE, SW_RESTORE, SW_SHOWMAXIMIZED = 6, 9, 3


def studio_window() -> int:
    """Studio's own window on this computer (0 when there is none: another system, Studio in a
    tab of a browser with more tabs, whose title says more than Studio's)."""
    if sys.platform != "win32":
        return 0
    import ctypes

    for title in TITLES:
        found: int = ctypes.windll.user32.FindWindowW(BROWSER_CLASS, title)
        if found:
            return found
    return 0


def show_window(window: int, how: int) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.ShowWindow(window, how)


def bring_forward(window: int) -> None:
    """A window the person is to work in, in front (a Java program being recorded): shown
    again if it was on the taskbar. Windows may refuse the front to a program in the
    background; the window is then only restored."""
    if sys.platform == "win32" and window:
        import ctypes

        user32 = ctypes.windll.user32
        if user32.IsIconic(window):
            user32.ShowWindow(window, SW_RESTORE)
        user32.SetForegroundWindow(window)


def is_maximized(window: int) -> bool:
    if sys.platform != "win32" or not window:
        return False
    import ctypes

    return bool(ctypes.windll.user32.IsZoomed(window))


@contextlib.contextmanager
def out_of_the_way(
    find: Callable[[], int] = studio_window,
    show: Callable[[int, int], None] = show_window,
    maximized: Callable[[int], bool] = is_maximized,
) -> Iterator[None]:
    """Studio's window goes down to the taskbar while a window the person works in is open (a
    demonstration, a sign-in), and comes back when it closes, as large as it was (restored
    from the taskbar, a maximized window came back smaller: the clean-Windows Lite test of
    12.10): Windows does not let that window come in front of Studio by itself (the
    clean-Windows test of 11.10, twice)."""
    window = find()
    was_maximized = bool(window) and maximized(window)
    if window:
        show(window, SW_MINIMIZE)
    try:
        yield
    finally:
        if window:
            show(window, SW_SHOWMAXIMIZED if was_maximized else SW_RESTORE)


def work_area() -> tuple[int, int] | None:
    """The screen without the taskbar (width, height), on Windows; None when unknown."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    spi_getworkarea = 0x0030
    if not ctypes.windll.user32.SystemParametersInfoW(spi_getworkarea, 0, ctypes.byref(rect), 0):
        return None
    return rect.right - rect.left, rect.bottom - rect.top


def window_command(
    browser: Path, url: str, profile: Path = PROFILE, area: tuple[int, int] | None = None
) -> list[str]:
    """``area``: the screen's work area; a window larger than it opens maximized (a laptop's
    1366x768: the clean-Windows test of 11.10 found Studio's buttons below the taskbar)."""
    width, height = SIZE
    smaller = area is not None and (area[0] < width or area[1] < height)
    return [
        str(browser),
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--start-maximized" if smaller else f"--window-size={width},{height}",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def app_browsers(machine: Machine | None = None) -> list[Path]:
    """Browsers that can show Studio as an app window here, the company's first."""
    found = browsers(machine or Machine())
    return [b.path for b in found if b.channel in ("msedge", "chrome") and b.path is not None]


def open_window(
    url: str,
    *,
    candidates: Sequence[Path] | None = None,
    start: Callable[[list[str]], object] = subprocess.Popen,
    profile: Path = PROFILE,
) -> bool:
    """Ask a browser here for the window; False when none could be started."""
    for browser in app_browsers() if candidates is None else candidates:
        try:
            start(window_command(browser, url, profile, work_area()))
        except OSError:
            continue
        return True
    return False


def window_open(profile: Path = PROFILE) -> bool:
    """Whether a browser holds the window's profile (its lockfile cannot be removed)."""
    lock = profile / "lockfile"
    if not lock.exists():
        return False
    try:
        lock.unlink()  # nobody holds it: the browser is gone (a new one makes it again)
    except OSError:
        return True
    return False


def watch(
    close: Callable[[], None],
    *,
    profile: Path = PROFILE,
    appears_s: float = APPEARS_S,
    every_s: float = 1.0,
    is_open: Callable[[Path], bool] = window_open,
) -> bool:
    """Wait for the window to close, then close Studio. False when the window never showed
    up: then Studio keeps running until it is stopped (Ctrl+C)."""
    deadline = time.monotonic() + appears_s
    while not is_open(profile):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.2)
    while is_open(profile):
        time.sleep(every_s)
    close()
    return True
