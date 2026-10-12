"""A demonstration in a Java program, recorded from Studio and Maptelo Lite (until 12.10 only
the command line could: ``maptelo record --java``). The page lists the Java programs open on
the desktop; the person picks one, works in it and comes back to say it is done."""

from __future__ import annotations

import shutil
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, ClassVar

import httpx2
import pytest

from maptelo.desktop.jab import Window
from maptelo.studio import Workspace, recording
from maptelo.studio.common import RunProblemError
from maptelo.studio.recording import RecordRequest, check_record
from maptelo.studio.server import running

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recordings"
TRACE = FIXTURES / "update_customer_price" / "01-login-single-version" / "trace.jsonl"
TOKEN = "klucz-testowy"
CHANGE = {"X-Maptelo-Token": TOKEN, "X-Maptelo": "1"}
SRK = Window(41, "SRK 4.2.7 - System Rozliczeń z Klientami [anowak]", 7, True)


def test_a_java_demonstration_needs_no_address(tmp_path: Path) -> None:
    wanted = RecordRequest.from_json({"process": "Ceny SRK", "java": "System Rozliczeń"})
    assert (wanted.process, wanted.java, wanted.url) == ("ceny-srk", "System Rozliczeń", "")
    if sys.platform == "win32":
        assert check_record(Workspace(tmp_path), wanted) == (None, None)
    else:
        with pytest.raises(RunProblemError) as refused:
            check_record(Workspace(tmp_path), wanted)
        assert refused.value.problems == ["a Java program can be recorded on Windows only"]


def test_a_web_demonstration_still_needs_its_address(tmp_path: Path) -> None:
    with pytest.raises(RunProblemError) as refused:
        check_record(Workspace(tmp_path), RecordRequest.from_json({"process": "Ceny"}))
    assert "the address must start with http:// or https://" in refused.value.problems


class FakeRecorder:
    """The Java recorder without a program: it writes a recorded trace when it stops."""

    made: ClassVar[list[FakeRecorder]] = []
    missing = False

    def __init__(self, folder: Path, options: Any) -> None:
        self.folder, self.options = folder, options
        self.stopped_by: str | None = None
        FakeRecorder.made.append(self)

    def start(self, timeout: float = 30.0) -> Window:
        if FakeRecorder.missing:
            raise RuntimeError("no Java window with 'SRK' in its title")
        self.folder.mkdir(parents=True)
        return SRK

    def record_until(
        self,
        *,
        stop_file: Path | None = None,
        timeout_s: float | None = None,
        stop: Callable[[], bool] | None = None,
        progress: Callable[[int], None] | None = None,
    ) -> Path:
        assert stop is not None
        assert progress is not None
        progress(3)
        while not stop():
            time.sleep(0.01)
        self.stopped_by = "Studio"
        shutil.copyfile(TRACE, self.folder / "trace.jsonl")
        return self.folder / "trace.jsonl"


@pytest.fixture
def fake_java(monkeypatch: pytest.MonkeyPatch) -> type[FakeRecorder]:
    FakeRecorder.made, FakeRecorder.missing = [], False
    monkeypatch.setattr("maptelo.capture.java.JavaRecorder", FakeRecorder)
    monkeypatch.setattr(recording, "ON_WINDOWS", True)
    return FakeRecorder


@pytest.fixture
def lite(tmp_path: Path) -> Iterator[tuple[httpx2.Client, Workspace]]:
    workspace = Workspace(tmp_path / "praca")
    with (
        running(workspace, TOKEN, lite=True) as base,
        httpx2.Client(base_url=base, headers=CHANGE, timeout=60) as client,
    ):
        yield client, workspace


def finished(client: httpx2.Client, job: str) -> dict[str, Any]:
    for _ in range(500):
        view: dict[str, Any] = client.get(f"/api/jobs/{job}").json()
        if view["state"] != "running":
            return view
        time.sleep(0.02)
    raise AssertionError("the recording did not end")


def test_lite_records_the_program_chosen_until_the_person_says_done(
    fake_java: type[FakeRecorder], lite: tuple[httpx2.Client, Workspace]
) -> None:
    client, workspace = lite
    started = client.post(
        "/api/recordings",
        json={"process": "Ceny SRK", "java": SRK.title, "note": "nowa cena", "private": True},
    )
    assert started.status_code == 202, started.text
    job = started.json()["id"]
    for _ in range(500):  # the recording has begun: the page says in which program
        events = client.get(f"/api/jobs/{job}").json()["events"]
        if any(e["type"] == "progress" for e in events):
            break
        time.sleep(0.02)
    begun = next(e for e in events if e["type"] == "start")
    assert begun["program"] == SRK.title
    assert client.post(f"/api/jobs/{job}/stop").status_code == 200
    done = finished(client, job)
    assert done["state"] == "stopped", done  # the person said it is done: all is kept
    (recorder,) = fake_java.made
    assert recorder.stopped_by == "Studio"
    options = recorder.options
    assert (options.window, options.process, options.title) == (SRK.title, "ceny-srk", "Ceny SRK")
    assert (options.note, options.private) == ("nowa cena", True)
    assert done["result"]["recording"] == recorder.folder.name
    assert recorder.folder.parent == workspace.recordings / "ceny-srk"


def test_a_program_not_open_is_said_so(
    fake_java: type[FakeRecorder], lite: tuple[httpx2.Client, Workspace]
) -> None:
    client, _ = lite
    fake_java.missing = True
    started = client.post("/api/recordings", json={"process": "Ceny SRK", "java": "SRK"})
    done = finished(client, started.json()["id"])
    assert done["state"] == "failed"
    assert done["error"].startswith("program Java „SRK” nie jest otwarty")


def test_the_page_lists_the_java_programs_open(
    monkeypatch: pytest.MonkeyPatch, lite: tuple[httpx2.Client, Workspace]
) -> None:
    client, _ = lite
    monkeypatch.setattr(recording, "ON_WINDOWS", True)
    monkeypatch.setattr("maptelo.desktop.jab.java_frames", lambda: [SRK])
    monkeypatch.setattr("maptelo.desktop.jab.find_dll", lambda extra=None: Path("jab.dll"))
    listed = client.get("/api/java/windows").json()
    assert listed == {"windows": [{"title": SRK.title}], "bridge": True, "problem": None}
    monkeypatch.setattr(recording, "ON_WINDOWS", False)
    elsewhere = client.get("/api/java/windows").json()
    assert elsewhere["windows"] == []
    assert elsewhere["problem"] == "program Java można nagrać tylko w Windows"
