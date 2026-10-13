"""Maptelo Lite: Studio that records a process and makes the map of one demonstration (its
steps, the SOP, the BPMN diagram, the report), and has no robot: what would run a process
answers that the full Maptelo does that."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest

from maptelo.studio import Workspace
from maptelo.studio.server import running

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recordings"
PROCESS = "update_customer_price"
TOKEN = "klucz-testowy"
CHANGE = {"X-Maptelo-Token": TOKEN, "X-Maptelo": "1"}


@pytest.fixture(autouse=True)
def own_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The language Lite keeps goes to a folder of the test, not the computer's ~/.maptelo."""
    monkeypatch.setattr("maptelo.browser.HOME", tmp_path / "home")


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    root = tmp_path / "praca"
    shutil.copytree(FIXTURES / PROCESS, root / "recordings" / PROCESS)
    return Workspace(root)


@pytest.fixture
def lite(workspace: Workspace) -> Iterator[httpx2.Client]:
    with (
        running(workspace, TOKEN, lite=True) as base,
        httpx2.Client(base_url=base, headers=CHANGE, timeout=60) as client,
    ):
        yield client


def test_a_demonstration_becomes_its_map(lite: httpx2.Client, workspace: Workspace) -> None:
    assert lite.get("/api/state").json()["lite"] is True
    first = workspace.recording_folders(PROCESS)[0].name
    (shown, *_) = lite.get(f"/api/recordings/{PROCESS}").json()
    assert shown["map"] is None
    made = lite.post("/api/maps", json={"process": PROCESS, "recording": first}).json()
    assert made["steps"] > 0
    folder = f"maps/{PROCESS}/{first}"
    assert made["map"]["report.html"] == f"{folder}/report.html"
    assert {"process.svg", "sop.md", "process.bpmn"} <= set(made["map"])
    report = lite.get(f"/api/files/{folder}/report.html")
    assert report.status_code == 200
    assert "<html" in report.text.lower()
    (again, *_) = lite.get(f"/api/recordings/{PROCESS}").json()
    assert again["map"] == made["map"]
    assert workspace.processes() == []  # a map of one demonstration is no robot's model
    assert lite.get("/api/processes").status_code == 404  # Lite serves no robot's processes
    missing = lite.post("/api/maps", json={"process": PROCESS, "recording": "nie-ma"})
    assert missing.status_code == 400
    assert "nie ma nagrania" in missing.json()["problems"][0]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/runs", {"process": PROCESS}),
        ("/api/build", {"process": PROCESS}),
        ("/api/agents/config", {}),
        ("/api/point", {}),
    ],
)
def test_no_robot_in_lite(lite: httpx2.Client, path: str, body: dict[str, object]) -> None:
    answer = lite.post(path, json=body)
    assert answer.status_code == 404
    assert answer.json()["problems"] == [
        "procesy uruchamia pełne Maptelo: Maptelo Lite tylko je mapuje"
    ]


def test_lite_answers_in_the_pages_language(lite: httpx2.Client) -> None:
    english = {"X-Maptelo-Lang": "en"}
    answer = lite.post("/api/runs", json={"process": PROCESS}, headers=english)
    assert answer.json()["problems"] == [
        "the full Maptelo runs processes: Maptelo Lite only maps them"
    ]
    nameless = lite.post("/api/recordings", json={"url": "https://x.test"}, headers=english)
    assert nameless.status_code == 400
    assert nameless.json()["problems"][0].startswith("the process needs a name")
    assert (
        lite.get("/api/environment", headers=english).json()["summary"]
        != (lite.get("/api/environment").json()["summary"])
    )


def test_the_language_chosen_is_kept(lite: httpx2.Client) -> None:
    assert lite.get("/api/state").json()["lang"] is None  # not chosen: the computer's
    assert lite.post("/api/language", json={"lang": "en"}).json() == {"lang": "en"}
    assert lite.get("/api/state").json()["lang"] == "en"
    wrong = lite.post("/api/language", json={"lang": "de"})
    assert wrong.status_code == 400
    assert wrong.json()["problems"] == ["język to pl albo en"]


def test_lite_speaks_of_itself_not_of_studio(lite: httpx2.Client) -> None:
    for language in ({}, {"X-Maptelo-Lang": "en"}):
        checks = lite.get("/api/environment", headers=language).json()["checks"]
        said = " ".join(f"{c['detail']} {c.get('hint') or ''}" for c in checks)
        assert "Studio" not in said
        assert "and run" not in said
        assert "i uruchamiać" not in said


def test_a_process_is_shown_by_the_name_it_was_given(
    lite: httpx2.Client, workspace: Workspace
) -> None:
    newest = workspace.recording_folders(PROCESS)[-1] / "trace.jsonl"
    header, rest = newest.read_text(encoding="utf-8").split("\n", 1)
    named = json.loads(header) | {"title": "Zmiana ceny klienta"}
    newest.write_text(json.dumps(named) + "\n" + rest, encoding="utf-8")
    (shown,) = lite.get("/api/drafts").json()
    assert (shown["process"], shown["title"]) == (PROCESS, "Zmiana ceny klienta")
    titles = [r["title"] for r in lite.get(f"/api/recordings/{PROCESS}").json()]
    assert titles[-1] == "Zmiana ceny klienta"


@pytest.fixture
def binned(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What goes to the Recycle Bin, kept by the test (the computer's own Bin stays as it was)."""
    thrown: list[str] = []

    def discard(paths: list[Path]) -> None:
        for path in paths:
            thrown.append(path.name)
            shutil.rmtree(path)

    monkeypatch.setattr("maptelo.studio.recording.discard", discard)
    return thrown


def test_a_recording_and_then_the_process_are_deleted(
    lite: httpx2.Client, workspace: Workspace, binned: list[str]
) -> None:
    first = workspace.recording_folders(PROCESS)[0].name
    lite.post("/api/maps", json={"process": PROCESS, "recording": first}).raise_for_status()
    asked_elsewhere = lite.delete(f"/api/recordings/{PROCESS}", headers={"X-Maptelo": "0"})
    assert asked_elsewhere.status_code == 403  # changes come only from Lite's own page
    gone = lite.delete(f"/api/recordings/{PROCESS}/{first}")
    assert gone.json()["removed"] == [f"recordings/{PROCESS}/{first}", f"maps/{PROCESS}/{first}"]
    assert first not in [folder.name for folder in workspace.recording_folders(PROCESS)]
    whole = lite.delete(f"/api/recordings/{PROCESS}")
    assert whole.json()["removed"] == [f"recordings/{PROCESS}", f"maps/{PROCESS}"]
    assert binned == [first, first, PROCESS, PROCESS]
    assert lite.get("/api/drafts").json() == []
    again = lite.delete(f"/api/recordings/{PROCESS}")
    assert again.status_code == 404
    assert again.json()["problems"] == [f"nie ma procesu '{PROCESS}'"]


def test_the_last_recording_deleted_takes_the_process_with_it(
    lite: httpx2.Client, workspace: Workspace, binned: list[str]
) -> None:
    for folder in workspace.recording_folders(PROCESS):
        lite.delete(f"/api/recordings/{PROCESS}/{folder.name}").raise_for_status()
    assert not (workspace.recordings / PROCESS).exists()
    assert lite.get("/api/drafts").json() == []
