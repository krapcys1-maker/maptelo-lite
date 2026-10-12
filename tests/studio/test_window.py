"""Studio in a window of its own: Edge or Chrome in app mode on Studio's own profile, the
next browser when one cannot start, and Studio closing when the window does."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from maptelo.studio import window
from maptelo.studio.window import (
    SW_MINIMIZE,
    SW_RESTORE,
    SW_SHOWMAXIMIZED,
    open_window,
    out_of_the_way,
    watch,
    window_command,
    window_open,
)

EDGE = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


def test_the_window_is_an_app_on_its_own_profile(tmp_path: Path) -> None:
    command = window_command(EDGE, "http://127.0.0.1:5000/?t=key", tmp_path / "profile")
    assert command[0] == str(EDGE)
    assert "--app=http://127.0.0.1:5000/?t=key" in command  # no tabs, no address bar
    assert f"--user-data-dir={tmp_path / 'profile'}" in command  # never the person's browsing
    assert "--no-first-run" in command
    assert not any("remote-debugging" in part for part in command)


def test_a_small_screen_gets_the_window_maximized(tmp_path: Path) -> None:
    """A laptop's 1366x768 (the clean-Windows test of 11.10: Studio's buttons were below the
    taskbar): the window opens maximized; on a large screen it keeps its own size."""
    small = window_command(EDGE, "http://x", tmp_path, area=(1366, 728))
    assert "--start-maximized" in small
    assert not any(part.startswith("--window-size") for part in small)
    large = window_command(EDGE, "http://x", tmp_path, area=(1920, 1040))
    assert "--window-size=1360,900" in large
    assert "--start-maximized" not in large


def test_the_next_browser_when_one_cannot_start() -> None:
    started: list[list[str]] = []

    def start(command: list[str]) -> object:
        if command[0] == str(EDGE):
            raise OSError("blocked by AppLocker")
        started.append(command)
        return object()

    assert open_window("http://x", candidates=[EDGE, CHROME], start=start)
    assert [c[0] for c in started] == [str(CHROME)]
    assert not open_window("http://x", candidates=[], start=start)  # the default browser then


def test_studio_closes_with_its_window() -> None:
    answers = iter([False, False, True, True, True, False])  # starting, open, then closed
    closed: list[bool] = []
    assert watch(lambda: closed.append(True), is_open=lambda p: next(answers), every_s=0)
    assert closed == [True]


def test_a_window_that_never_shows_up_leaves_studio_running() -> None:
    closed: list[bool] = []
    assert not watch(lambda: closed.append(True), is_open=lambda p: False, appears_s=0.3)
    assert closed == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows keeps an open file from being removed")
def test_the_profile_says_whether_the_window_is_open(tmp_path: Path) -> None:
    assert not window_open(tmp_path)  # no lockfile: no browser on the profile
    lock = tmp_path / "lockfile"
    with lock.open("w"):  # a browser holds it while its window is open
        assert window_open(tmp_path)
    assert not window_open(tmp_path)  # let go of: closed (and the stale file is cleared)
    assert not lock.exists()


def test_the_window_profile_is_studios_own() -> None:
    assert window.PROFILE.parts[-2:] == (".maptelo", "studio-window")


def test_studio_steps_aside_while_a_browser_window_is_worked_in() -> None:
    """A demonstration's or a sign-in's window opened behind Studio's (the clean-Windows test of
    11.10, twice): Studio goes down to the taskbar while it is open and comes back after, also
    when the work fails; without a window of its own Studio touches nothing."""
    shown: list[tuple[int, int]] = []
    with out_of_the_way(find=lambda: 42, show=lambda w, how: shown.append((w, how))):
        assert shown == [(42, SW_MINIMIZE)]
    assert shown == [(42, SW_MINIMIZE), (42, SW_RESTORE)]
    shown.clear()
    with (
        pytest.raises(RuntimeError),
        out_of_the_way(find=lambda: 42, show=lambda w, how: shown.append((w, how))),
    ):
        raise RuntimeError("the browser did not start")
    assert shown[-1] == (42, SW_RESTORE)
    shown.clear()
    with out_of_the_way(find=lambda: 0, show=lambda w, how: shown.append((w, how))):
        pass
    assert shown == []
    # a maximized window comes back maximized (restored, it came back smaller: 12.10)
    with out_of_the_way(
        find=lambda: 42, show=lambda w, how: shown.append((w, how)), maximized=lambda w: True
    ):
        pass
    assert shown == [(42, SW_MINIMIZE), (42, SW_SHOWMAXIMIZED)]
