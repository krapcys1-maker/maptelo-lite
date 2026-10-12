"""What was written while Maptelo was called Stepproof still works: recordings, the folder in
the person's home with signed-in profiles, and IT's policy where the old name put it."""

from __future__ import annotations

from pathlib import Path

import pytest

from maptelo import formerly, policy
from maptelo.policy import policy_path
from maptelo.trace import TRACE_FORMAT, load_trace

FIXTURE = (
    Path(__file__).parent / "fixtures/recordings/update_customer_price/01-login-single-version"
)


def test_a_recording_made_before_the_rename_is_read_as_todays(tmp_path: Path) -> None:
    text = (FIXTURE / "trace.jsonl").read_text(encoding="utf-8")
    old = text.replace(TRACE_FORMAT, "stepproof-trace/0.1", 1).replace(
        '"source":"maptelo-recorder"', '"source":"stepproof-recorder"', 1
    )
    assert '"stepproof-trace/0.1"' in old
    assert '"stepproof-recorder"' in old
    (tmp_path / "trace.jsonl").write_text(old, encoding="utf-8")
    trace = load_trace(tmp_path)
    assert trace.header.format == TRACE_FORMAT
    assert trace.header.source == "maptelo-recorder"
    assert len(trace.events) == len(load_trace(FIXTURE).events)
    assert "stepproof" not in trace.header.model_dump_json()  # saved again under the new name


def test_the_old_home_folder_is_moved_when_first_needed(tmp_path: Path) -> None:
    home, old_home = tmp_path / ".maptelo", tmp_path / ".stepproof"
    (old_home / "profiles" / "praca").mkdir(parents=True)
    (old_home / "profiles" / "praca" / formerly.COOKIES).write_text("{}", encoding="utf-8")

    profiles = formerly.carried(home / "profiles", home, old_home)
    assert profiles == home / "profiles"
    assert (profiles / "praca" / formerly.COOKIES).is_file()
    assert not (old_home / "profiles").exists()
    # once moved, the new folder is used; whatever is new in the old one is left alone
    (old_home / "profiles" / "inny").mkdir(parents=True)
    assert formerly.carried(home / "profiles", home, old_home) == home / "profiles"
    assert (old_home / "profiles" / "inny").is_dir()


def test_a_folder_that_cannot_be_moved_is_used_where_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, old_home = tmp_path / ".maptelo", tmp_path / ".stepproof"
    (old_home / "profiles" / "praca").mkdir(parents=True)

    def refuse(self: Path, target: Path) -> Path:
        raise PermissionError("a browser has the profile open")

    monkeypatch.setattr(Path, "rename", refuse)
    assert formerly.carried(home / "profiles", home, old_home) == old_home / "profiles"


def test_paths_outside_the_home_folder_are_left_as_they_are(tmp_path: Path) -> None:
    old_home = tmp_path / ".stepproof"
    (old_home / "profiles").mkdir(parents=True)
    given = tmp_path / "elsewhere" / "profiles"
    assert formerly.carried(given, tmp_path / ".maptelo", old_home) == given
    assert (old_home / "profiles").is_dir()


def test_a_profile_keeps_its_sign_in_kept_under_the_old_name(tmp_path: Path) -> None:
    (tmp_path / formerly.COOKIES).write_text('{"cookies": []}', encoding="utf-8")
    kept = formerly.carried_cookies(tmp_path, "maptelo-cookies.json")
    assert kept == tmp_path / "maptelo-cookies.json"
    assert kept.read_text(encoding="utf-8") == '{"cookies": []}'
    assert not (tmp_path / formerly.COOKIES).exists()
    assert formerly.carried_cookies(tmp_path / "nowy", "maptelo-cookies.json") == (
        tmp_path / "nowy" / "maptelo-cookies.json"
    )


def test_its_policy_still_applies_where_the_old_name_put_it(tmp_path: Path) -> None:
    named = tmp_path / "zasady.yaml"
    assert policy_path({formerly.POLICY_ENV: str(named)}) == named
    assert policy_path(
        {policy.POLICY_ENV: str(tmp_path / "nowe.yaml"), formerly.POLICY_ENV: str(named)}
    ) == (tmp_path / "nowe.yaml")
    old = Path("C:/ProgramData/Stepproof/policy.yaml")
    new = Path("C:/ProgramData/Maptelo/policy.yaml")
    data = {"ProgramData": "C:/ProgramData"}
    assert policy_path(data, exists=lambda p: p == old) == old
    assert policy_path(data, exists=lambda p: p in (old, new)) == new
