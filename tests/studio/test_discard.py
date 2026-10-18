"""Deleting into the Recycle Bin is asked again while Windows says another program holds a
file (an antivirus scanning the new screenshots, Explorer's preview): code 1224 at a person's
first try was no reason to give up. Any other answer is told at once."""

from pathlib import Path

import pytest

from maptelo.studio import discard


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(discard.time, "sleep", lambda seconds: None)
    made = tmp_path / "20261018-0701"
    made.mkdir()
    (made / "trace.jsonl").write_text("{}\n", encoding="utf-8")
    return made


def answers(monkeypatch: pytest.MonkeyPatch, said: list[int]) -> list[list[Path]]:
    """Windows answers these codes in turn; 0 moves the folders away."""
    asked: list[list[Path]] = []

    def shell_delete(paths: list[Path]) -> tuple[int, bool]:
        asked.append(list(paths))
        code = said.pop(0)
        if code == 0:
            for path in paths:
                (path / "trace.jsonl").unlink()
                path.rmdir()
        return code, False

    monkeypatch.setattr(discard, "_shell_delete", shell_delete)
    return asked


def test_a_file_held_for_a_moment_is_deleted_at_the_next_try(folder, monkeypatch) -> None:
    asked = answers(monkeypatch, [1224, 32, 0])
    discard._recycle([folder])
    assert len(asked) == 3
    assert not folder.exists()


def test_a_file_held_all_along_says_so(folder, monkeypatch) -> None:
    asked = answers(monkeypatch, [1224] * discard.TRIES)
    with pytest.raises(OSError, match=r"still in use \(Windows says 1224\)"):
        discard._recycle([folder])
    assert len(asked) == discard.TRIES
    assert folder.exists()


def test_another_answer_is_told_at_once(folder, monkeypatch) -> None:
    asked = answers(monkeypatch, [5])
    with pytest.raises(OSError, match=r"could not be deleted \(Windows says 5\)"):
        discard._recycle([folder])
    assert len(asked) == 1


def test_what_went_to_the_bin_already_is_not_asked_again(folder, tmp_path, monkeypatch) -> None:
    own_map = tmp_path / "map"
    own_map.mkdir()
    (own_map / "trace.jsonl").write_text("{}\n", encoding="utf-8")
    asked: list[list[Path]] = []

    def shell_delete(paths: list[Path]) -> tuple[int, bool]:
        asked.append(list(paths))
        if len(asked) == 1:  # the map went, the recording's file was held
            (own_map / "trace.jsonl").unlink()
            own_map.rmdir()
            return 1224, False
        for path in paths:
            (path / "trace.jsonl").unlink()
            path.rmdir()
        return 0, False

    monkeypatch.setattr(discard, "_shell_delete", shell_delete)
    discard._recycle([folder, own_map])
    assert asked == [[folder, own_map], [folder]]
