"""Maptelo Lite: Studio that records a process and makes the map of one demonstration (its
steps, the SOP, the BPMN diagram, the report), and has no robot: what would run a process
answers that the full Maptelo does that."""

from __future__ import annotations

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
