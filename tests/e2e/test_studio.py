"""M9: Studio runs a process on MiniERP, from a sheet or one record, with proof; the page
shows it as it happens."""

from __future__ import annotations

import csv
import time
from functools import partial
from pathlib import Path
from typing import Any

import httpx2
import pytest
from playwright.sync_api import Browser, expect

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


def versions(api: httpx2.Client, customer: str, cpn: str) -> int:
    return len(api.get(f"/api/products/{customer}/{cpn}/versions").json())


def test_a_sheet_runs_from_studio_with_proof(
    browser: Browser, live_server: str, api: httpx2.Client, tmp_path: Path
) -> None:
    workspace = studio_workspace(tmp_path / "praca", live_server)
    session = signed_in(browser, live_server, tmp_path / "session.json")
    sheet = (
        b"customer;cpn;new_price;valid_from\n"
        b"C002;51001-A;47.00;2026-12-01\n"
        b"C001;99999-Z;10.00;2026-12-01\n"
    )
    with (
        running(workspace, TOKEN) as base,
        httpx2.Client(base_url=base, headers=CHANGE, timeout=30) as studio,
    ):
        kept = studio.post("/api/sheets", params={"name": "ceny.csv"}, content=sheet).json()
        started = studio.post(
            "/api/runs",
            json={"process": "ceny", "sheet": kept["sheet"], "session": str(session),
                  "timeout_ms": 6000},
        )  # fmt: skip
        assert started.status_code == 202, started.text
        done = finished(studio, started.json()["id"])
        busy_free = studio.get("/api/state").json()["job"]
        latest = studio.get("/api/processes/ceny").json()["last_run"]

    assert done["state"] == "done", done["error"]
    kinds = [event["type"] for event in done["events"]]
    assert (kinds[0], kinds[-1], kinds.count("record"), kinds.count("result")) == (
        "start", "end", 2, 2
    )  # fmt: skip
    results = [event for event in done["events"] if event["type"] == "result"]
    assert [r["outcome"] for r in results] == ["VERIFIED", "BUSINESS_EXCEPTION"]
    assert results[0]["evidence"]
    assert all((workspace.root / shot).is_file() for shot in results[0]["evidence"])
    assert done["result"]["counts"] == {"VERIFIED": 1, "BUSINESS_EXCEPTION": 1}
    assert versions(api, "C002", "51001-A") == 2  # written once, and confirmed by a read

    with (workspace.root / done["result"]["results_file"]).open(encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file, delimiter=";"))
    assert [row["Maptelo outcome"] for row in rows] == ["VERIFIED", "BUSINESS_EXCEPTION"]
    assert busy_free["state"] == "done"
    assert latest["summary"]["outcomes"] == {"VERIFIED": 1, "BUSINESS_EXCEPTION": 1}


def test_records_run_again_at_the_end_keep_their_rows(
    browser: Browser, live_server: str, api: httpx2.Client, tmp_path: Path
) -> None:
    """The system of record cannot be read (503), so neither record can be checked for being
    done: both write nothing, end in a system failure and run once more at the end. The page
    shows them as their own rows again (the clean-Windows test of 12.10: Studio counted the
    starts, the record run again was a row after the last one, and the run ended in „list index
    out of range”)."""
    api.put("/api/testbed/chaos", json={"read_error_rate": 1.0}).raise_for_status()
    workspace = studio_workspace(tmp_path / "praca", live_server)
    session = signed_in(browser, live_server, tmp_path / "session.json")
    sheet = (
        b"customer;cpn;new_price;valid_from\n"
        b"C002;51001-A;47.00;2026-12-01\n"
        b"C001;48211-A;316.00;2026-12-01\n"
    )
    with (
        running(workspace, TOKEN) as base,
        httpx2.Client(base_url=base, headers=CHANGE, timeout=30) as studio,
    ):
        kept = studio.post("/api/sheets", params={"name": "ceny.csv"}, content=sheet).json()
        started = studio.post(
            "/api/runs",
            json={"process": "ceny", "sheet": kept["sheet"], "session": str(session),
                  "timeout_ms": 6000},
        )  # fmt: skip
        done = finished(studio, started.json()["id"], timeout=240)
    assert done["state"] == "done", done["error"]
    rows = [e["number"] for e in done["events"] if e["type"] == "record"]
    assert rows == [1, 2, 1, 2]
    assert all(e["number"] in (1, 2) for e in done["events"] if e["type"] == "result")
    assert versions(api, "C002", "51001-A") == 1  # nothing written, twice


def test_a_run_stops_on_request_and_says_what_is_left(
    browser: Browser, live_server: str, api: httpx2.Client, tmp_path: Path
) -> None:
    workspace = studio_workspace(tmp_path / "praca", live_server)
    session = signed_in(browser, live_server, tmp_path / "session.json")
    rows = "".join(f"C002;51001-A;4{n}.00;2026-12-0{n}\n" for n in range(1, 8))
    sheet = ("customer;cpn;new_price;valid_from\n" + rows).encode()
    with (
        running(workspace, TOKEN) as base,
        httpx2.Client(base_url=base, headers=CHANGE, timeout=30) as studio,
    ):
        kept = studio.post("/api/sheets", params={"name": "ceny.csv"}, content=sheet).json()
        job = studio.post(
            "/api/runs", json={"process": "ceny", "sheet": kept["sheet"], "session": str(session)}
        ).json()["id"]
        one = {
            "customer": "C001",
            "cpn": "48212-B",
            "new_price": "135.00",
            "valid_from": "2026-12-01",
        }
        second = studio.post(
            "/api/runs", json={"process": "ceny", "inputs": one, "session": str(session)}
        )
        assert second.status_code == 409  # one run at a time
        assert "Najpierw zakończ" in second.json()["problems"][0]
        studio.post(f"/api/jobs/{job}/stop")
        done = finished(studio, job)
    assert done["state"] == "stopped"
    assert done["result"]["not_run"] >= 1
    # the reason in the page's words: a request, never the safety stop after failures in a row
    assert (
        done["result"]["stopped_early"]
        == "zatrzymano na prośbę; uruchom ponownie, żeby zrobić resztę"
    )
    assert versions(api, "C002", "51001-A") == 1 + done["result"]["ran"]


def test_the_computer_is_checked_from_studio(
    browser: Browser, live_server: str, tmp_path: Path
) -> None:
    workspace = studio_workspace(tmp_path / "praca", live_server)
    session = signed_in(browser, live_server, tmp_path / "session.json")
    with (
        running(workspace, TOKEN) as base,
        httpx2.Client(base_url=base, headers=CHANGE, timeout=30) as studio,
    ):
        started = studio.post("/api/doctor", json={"process": "ceny", "session": str(session)})
        assert started.status_code == 202, started.text
        done = finished(studio, started.json()["id"])
    assert done["state"] == "done", done
    verdicts = {c["what"]: c["verdict"] for c in done["result"]["checks"]}
    assert done["result"]["ready"] is True, done["result"]["checks"]
    assert verdicts["independent read"] == "ok"
    assert verdicts["browser"] == "ok"


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


def test_a_slow_page_left_behind_does_not_paint_over_the_next(
    browser: Browser, live_server: str, tmp_path: Path
) -> None:
    """Found while taking pictures for the website: the list of processes, slow to load,
    arrived after the person had moved on and replaced the page they were reading."""
    workspace = studio_workspace(tmp_path / "praca", live_server)
    with running(workspace, TOKEN) as base:
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{base}/?t={TOKEN}")
        expect(page.get_by_role("heading", name="Procesy")).to_be_visible()
        page.evaluate(
            """() => {  // from now on the list of processes answers slowly
              const original = window.fetch;
              window.fetch = (input, init) => /\\/api\\/processes$/.test(String(input))
                ? new Promise((done) => setTimeout(done, 900)).then(() => original(input, init))
                : original(input, init);
            }"""
        )
        page.evaluate("() => { location.hash = '#/p/ceny'; }")
        expect(page.get_by_role("heading", name="Zmiana ceny klienta")).to_be_visible()
        page.evaluate("() => { location.hash = '#/'; }")  # the slow list starts loading
        page.wait_for_timeout(200)
        page.evaluate("() => { location.hash = '#/runs'; }")
        expect(page.get_by_role("heading", name="Przebiegi")).to_be_visible()
        page.wait_for_timeout(1500)  # the slow answer arrives meanwhile
        expect(page.get_by_role("heading", name="Przebiegi")).to_be_visible()
        expect(page.get_by_role("heading", name="Procesy")).to_have_count(0)
        context.close()


def test_the_page_runs_one_record_and_shows_the_proof(
    browser: Browser, live_server: str, api: httpx2.Client, tmp_path: Path
) -> None:
    workspace = studio_workspace(tmp_path / "praca", live_server)
    session = signed_in(browser, live_server, tmp_path / "session.json")
    with running(workspace, TOKEN) as base:
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.goto(f"{base}/?t={TOKEN}")
        expect(page.get_by_role("heading", name="Procesy")).to_be_visible()
        page.get_by_role("link", name="Zmiana ceny klienta").click()
        expect(page.get_by_role("heading", name="Zmiana ceny klienta")).to_be_visible()
        page.get_by_role("button", name="Jeden rekord").click()
        page.get_by_label("Kod klienta").fill("C002")
        page.get_by_label("Customer part number").fill("51001-A")
        page.get_by_label("Nowa cena w walucie produktu").fill("47.00")
        page.get_by_label("Od kiedy obowiązuje nowa cena").fill("2026-12-01")
        page.get_by_label("Albo zapisana sesja").fill(str(session))
        page.get_by_role("button", name="Uruchom", exact=True).click()
        expect(page.get_by_text("Zakończony")).to_be_visible(timeout=60_000)
        expect(page.get_by_text("Potwierdzone")).to_be_visible()
        expect(page.get_by_text("Wiersz potwierdzony niezależnym odczytem.")).to_be_visible()
        expect(page.get_by_role("img", name="Zrzut ekranu z wiersza 1")).to_be_visible()
        page.get_by_role("link", name="Przebiegi").click()
        expect(page.get_by_role("cell", name="Zmiana ceny klienta")).to_be_visible()
        context.close()
    assert versions(api, "C002", "51001-A") == 2


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
    assert drafts == [{"process": "ceny", "recordings": 1}]
