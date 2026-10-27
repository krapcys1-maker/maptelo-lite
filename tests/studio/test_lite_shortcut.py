"""The shortcut of the portable Lite waits in its console until Lite says it is ready, or why it
could not start (19.10: the first start took a minute with nothing on the screen, and the person
took Lite for broken). Lite tells it in the file the shortcut names; started otherwise, nothing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from maptelo import lite
from maptelo.studio import server


def run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, serve: Any, told: Path | None) -> Any:
    if told is None:
        monkeypatch.delenv(lite.STARTED, raising=False)
    else:
        monkeypatch.setenv(lite.STARTED, str(told))
    monkeypatch.setattr(server, "serve", serve)
    monkeypatch.setattr("maptelo.studio.serve", serve)
    args = ["studio", "--workspace", str(tmp_path / "Procesy"), "--data", str(tmp_path / "data")]
    return CliRunner().invoke(lite.app, args)


def test_the_shortcut_is_told_when_the_window_opens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    told = tmp_path / "started.txt"

    def serve(_: object, *, announce: Any, **__: object) -> None:
        assert not told.exists()  # not before the address is known
        announce("http://127.0.0.1:5000/?t=key")
        announce("the window was closed: Studio stops")

    result = run(monkeypatch, tmp_path, serve, told)
    assert result.exit_code == 0, result.output
    assert told.read_text(encoding="utf-8") == "ready"


def test_the_shortcut_is_told_why_lite_could_not_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    told = tmp_path / "started.txt"

    def serve(*_: object, **__: object) -> None:
        raise OSError("the port is taken")

    result = run(monkeypatch, tmp_path, serve, told)
    assert result.exit_code != 0
    assert told.read_text(encoding="utf-8") == "failed: the port is taken"


def test_lite_started_otherwise_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def serve(_: object, *, announce: Any, **__: object) -> None:
        announce("http://127.0.0.1:5000/?t=key")

    result = run(monkeypatch, tmp_path, serve, None)
    assert result.exit_code == 0, result.output
    assert not list(tmp_path.glob("**/started.txt"))
