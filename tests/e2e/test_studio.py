"""Studio on MiniERP, end to end: a demonstration recorded, a profile signed in; and in the
full Maptelo (M9) a process run from a sheet or one record, with proof, shown as it happens."""

from __future__ import annotations

import time
from functools import partial
from pathlib import Path
from typing import Any

import httpx2
import pytest
from playwright.sync_api import Browser

from maptelo.capture import record_session
from maptelo.studio import Workspace, recording
from maptelo.studio.server import running
from minierp.scenarios import login

pytestmark = pytest.mark.e2e
EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "update_customer_price.yaml"
TOKEN = "klucz-e2e"
CHANGE = {"X-Maptelo-Token": TOKEN, "X-Maptelo": "1"}


def studio_workspace(root: Path, live_server: str) -> Workspace:
    folder = root / "maps" / "ceny"
    folder.mkdir(parents=True)
    model = EXAMPLE.read_text(encoding="utf-8").replace("http://127.0.0.1:8000", live_server)
    (folder / "model.yaml").write_text(model, encoding="utf-8")
    return Workspace(root)


def signed_in(browser: Browser, live_server: str, path: Path) -> Path:
    context = browser.new_context()
    login(context.new_page(), live_server)
    context.storage_state(path=str(path))
    context.close()
    return path


def finished(studio: httpx2.Client, job: str, timeout: float = 180) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view: dict[str, Any] = studio.get(f"/api/jobs/{job}").json()
        if view["state"] != "running":
            return view
        time.sleep(0.2)
    raise AssertionError(f"job {job} still running after {timeout} s")


def test_a_profile_signs_in_from_studio(
    live_server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window opens on the profile at the address; when it closes (here: stopped), the
    profile keeps what the browser holds. The test window is headless and the profile lives
    in a temporary folder, never in the person's ~/.maptelo."""
    from maptelo import browser as browsers
    from maptelo.studio import readiness

    monkeypatch.setattr(browsers, "PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(readiness, "PROFILES", tmp_path / "profiles")
    opened = readiness.profile_context
    monkeypatch.setattr(
        readiness, "profile_context", lambda *a, **k: opened(*a, **{**k, "headless": True})
    )
    workspace = studio_workspace(tmp_path / "praca", live_server)
    with (
        running(workspace, TOKEN) as base,
        httpx2.Client(base_url=base, headers=CHANGE, timeout=30) as studio,
    ):
        started = studio.post(
            "/api/profiles/sign-in", json={"profile": "praca", "url": f"{live_server}/login"}
        )
        assert started.status_code == 202, started.text
        job = started.json()["id"]
        deadline = time.monotonic() + 60
        while not any(e["type"] == "open" for e in studio.get(f"/api/jobs/{job}").json()["events"]):
            assert time.monotonic() < deadline, "the sign-in window never opened"
            time.sleep(0.2)
        studio.post(f"/api/jobs/{job}/stop")
        done = finished(studio, job)
        listed = studio.get("/api/profiles").json()
    assert done["state"] == "stopped", done  # "Zakończ" in Studio: as normal as closing it
    assert done["result"] == {"profile": "praca", "kept": True}
    assert [p["name"] for p in listed] == ["praca"]
    assert listed[0]["signed_in"] is not None


def test_a_demonstration_is_recorded_from_studio(
    browser: Browser,
    live_server: str,
    api: httpx2.Client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a person would see the window; here nobody watches, so it has none
    monkeypatch.setattr(recording, "record_session", partial(record_session, headless=True))
    workspace = Workspace(tmp_path / "praca")
    session = signed_in(browser, live_server, tmp_path / "session.json")
    with (
        running(workspace, TOKEN) as base,
        httpx2.Client(base_url=base, headers=CHANGE, timeout=30) as studio,
    ):
        started = studio.post(
            "/api/recordings",
            json={"process": "ceny", "url": f"{live_server}/pricing", "session": str(session),
                  "note": "pokaz z testu"},
        )  # fmt: skip
        assert started.status_code == 202, started.text
        job = started.json()["id"]
        deadline = time.monotonic() + 30
        while not any(
            e["type"] == "start" for e in studio.get(f"/api/jobs/{job}").json()["events"]
        ):
            assert time.monotonic() < deadline
            time.sleep(0.1)
        time.sleep(1.5)  # the page opens and the recorder notes it
        studio.post(f"/api/jobs/{job}/stop")
        done = finished(studio, job)
        listed = studio.get("/api/recordings/ceny").json()
        drafts = studio.get("/api/drafts").json()
    assert done["state"] == "stopped", done["error"]
    folder = workspace.root / done["result"]["folder"]
    assert done["result"]["folder"].startswith("recordings/ceny/")
    assert (folder / "trace.jsonl").is_file()
    assert done["result"]["actions"] >= 1  # at least the opening of the start page
    assert [(r["note"], r["ended"]) for r in listed] == [("pokaz z testu", "stopped")]
    assert drafts == [{"process": "ceny", "title": None, "recordings": 1}]
