"""The assistant in Studio: its settings page (the key typed once and never shown again, the
person's agreement, a connection check), a review of a process beside Studio's one job, its
advice beside the process, and the automat stopping where a person decides. The AI is a fake
server at a custom address, as a company's gateway would be."""

from __future__ import annotations

import json
import shutil
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx2
import pytest

from maptelo import browser
from maptelo.studio import Workspace
from maptelo.studio.server import running

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recordings"
PROCESS = "update_customer_price"
TOKEN = "klucz-testowy"
CHANGE = {"X-Maptelo-Token": TOKEN, "X-Maptelo": "1"}
KEY = "firm-key-0123456789"
REVIEW = {
    "summary": "Odpowiedz na pytanie o okno potwierdzenia.",
    "hints": [
        {"kind": "answer", "about": "why.confirm_price_change", "severity": "important",
         "title": "Reguła okna potwierdzenia", "detail": "Tak było w nagraniu 05.",
         "answer": "zmiana ceny o więcej niż 20%"},
        {"kind": "step", "about": "click_save", "severity": "warning",
         "title": "Zapis bez sprawdzenia wyniku", "detail": "Dodaj sprawdzenie."},
    ],
}  # fmt: skip


class FakeAi:
    def __init__(self) -> None:
        self.questions: list[dict[str, Any]] = []
        self.keys: list[str | None] = []


@pytest.fixture
def ai() -> Iterator[tuple[FakeAi, str]]:
    fake = FakeAi()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, data: Any) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_GET(self) -> None:
            self._send({"data": [{"id": "firm-model"}]})

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            fake.questions.append(body)
            fake.keys.append(self.headers.get("api-key"))
            asked = body["messages"][-1]["content"]
            answer = {"ok": True} if '{"ok": true}' in asked else REVIEW
            self._send({"choices": [{"message": {"content": json.dumps(answer)},
                                     "finish_reason": "stop"}], "usage": {}})  # fmt: skip

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield fake, f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    monkeypatch.setattr(browser, "HOME", tmp_path / "home")  # settings and keys of this test
    (tmp_path / "policy.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("MAPTELO_POLICY", str(tmp_path / "policy.yaml"))
    root = tmp_path / "praca"
    shutil.copytree(FIXTURES / PROCESS, root / "recordings" / PROCESS)
    return Workspace(root)


@pytest.fixture
def studio(workspace: Workspace) -> Iterator[httpx2.Client]:
    with (
        running(workspace, TOKEN) as base,
        httpx2.Client(base_url=base, headers=CHANGE, timeout=60) as client,
    ):
        yield client


def settle(studio: httpx2.Client, key: str) -> dict[str, Any]:
    for _ in range(200):
        shown: dict[str, Any] = studio.get(f"/api/processes/{key}/assistant").json()
        if not shown["review"] or shown["review"]["state"] != "running":
            return shown
        time.sleep(0.05)
    raise AssertionError("the review did not finish")


def turn_on(studio: httpx2.Client, url: str, mode: str = "assistant") -> dict[str, Any]:
    settings = {"mode": mode, "provider": "custom", "base_url": url, "model": "firm-model",
                "key_header": "api-key", "watch": False}  # fmt: skip
    assert studio.post("/api/assistant/settings", json=settings).status_code == 200
    kept = studio.post("/api/assistant/key", json={"provider": "custom", "key": KEY})
    assert kept.status_code == 200
    agreed: dict[str, Any] = studio.post("/api/assistant/agree").json()
    return agreed


def test_the_settings_page(studio: httpx2.Client, ai: tuple[FakeAi, str]) -> None:
    fake, url = ai
    shown = studio.get("/api/assistant").json()
    assert shown["settings"]["mode"] == "off"
    assert [p["name"] for p in shown["providers"]] == ["deepseek", "anthropic", "openai",
                                                       "custom", "local"]  # fmt: skip
    deepseek = shown["providers"][0]
    assert deepseek["leaves_company"]
    assert "Chinach" in deepseek["note"]
    wrong = studio.post("/api/assistant/settings", json={"mode": "always"})
    assert wrong.status_code == 400
    assert wrong.json()["problems"][0].startswith("mode")
    agreed = turn_on(studio, url)
    assert KEY not in json.dumps(agreed)
    custom = next(p for p in agreed["providers"] if p["name"] == "custom")
    assert custom["key"] == {"source": "saved", "ending": "…6789"}
    assert agreed["agreed"]
    assert agreed["destination"] == "custom@" + url.split("/")[2]
    checked = studio.post("/api/assistant/check").json()
    assert checked == {"ok": True, "label": f"firm-model at {url.split('/')[2]}",
                       "models": ["firm-model"]}  # fmt: skip
    assert fake.keys[-1] == KEY  # in the header the company's gateway wants
    bad = studio.post("/api/assistant/key", json={"provider": "custom", "key": "two words"})
    assert bad.json()["problems"] == ["nieprawidłowy klucz: zawiera spacje lub jest za długi"]
    forgotten = studio.post("/api/assistant/key/forget", json={"provider": "custom"}).json()
    assert (
        next(p for p in forgotten["providers"] if p["name"] == "custom")["key"]["source"] == "none"
    )


def test_a_review_without_ai_and_with_it(
    studio: httpx2.Client, workspace: Workspace, ai: tuple[FakeAi, str]
) -> None:
    fake, url = ai
    assert studio.post("/api/build", json={"process": PROCESS}).status_code == 200
    assert studio.post(f"/api/processes/{PROCESS}/assistant/review", json={}).status_code == 202
    off = settle(studio, PROCESS)
    assert off["mode"] == "off"
    assert fake.questions == []
    assert (
        off["advice"]["problem"]
        == "asystent AI jest wyłączony: można go włączyć w ustawieniach asystenta"
    )
    assert {h["source"] for h in off["advice"]["hints"]} == {"maptelo"}
    turn_on(studio, url)
    assert studio.post(f"/api/processes/{PROCESS}/assistant/review", json={}).status_code == 202
    on = settle(studio, PROCESS)
    ai_hints = [h for h in on["advice"]["hints"] if h["source"] == "ai"]
    assert [h["title"] for h in ai_hints] == ["Reguła okna potwierdzenia",
                                              "Zapis bez sprawdzenia wyniku"]  # fmt: skip
    assert ai_hints[0]["answer"] == "zmiana ceny o więcej niż 20%"
    sent = fake.questions[-1]["messages"][1]["content"]
    assert "48212-B" not in sent  # a typed part number went out as a mark
    details = studio.get(f"/api/processes/{PROCESS}").json()
    assert details["assistant"] == {"hints": 2, "answers": 1, "running": False}
    assert any(e["what"] == "review" for e in on["journal"])


def test_the_assistant_watches_a_build(studio: httpx2.Client, ai: tuple[FakeAi, str]) -> None:
    _, url = ai
    turn_on(studio, url)
    studio.post("/api/assistant/settings", json={"watch": True})
    assert studio.post("/api/build", json={"process": PROCESS}).status_code == 200
    time.sleep(0.05)
    shown = settle(studio, PROCESS)
    assert shown["advice"]["stage"] == "build"
    assert shown["advice"]["by"]


def test_the_automat_stops_where_a_person_decides(
    studio: httpx2.Client, ai: tuple[FakeAi, str]
) -> None:
    _, url = ai
    turn_on(studio, url)
    refused = studio.post("/api/assistant/autopilot", json={"process": PROCESS})
    assert refused.json()["problems"] == [
        "automat jest wyłączony: można go włączyć w ustawieniach asystenta"
    ]
    studio.post("/api/assistant/settings", json={"mode": "autopilot"})
    job = studio.post("/api/assistant/autopilot", json={"process": PROCESS}).json()
    for _ in range(400):
        done = studio.get(f"/api/jobs/{job['id']}?after=0").json()
        if done["state"] != "running":
            break
        time.sleep(0.05)
    assert done["state"] == "done", done
    report = done["result"]
    assert [(s["name"], s["state"]) for s in report["stages"]] == [
        ("build", "done"),
        ("review", "done"),
        ("questions", "stopped"),
    ]
    assert report["stages"][2]["said"] == (
        "Pytania oczekujące na odpowiedź: 4; propozycje odpowiedzi AI: 1."
    )
    assert report["waits_for"] == [
        "Wymagane odpowiedzi na pytania (propozycje AI są widoczne przy pytaniach), a następnie "
        "ponowne uruchomienie automatu."
    ]
    assert not report["finished"]
    questions = studio.get(f"/api/processes/{PROCESS}/questions").json()["questions"]
    assert all(q["answer"] is None for q in questions)  # the automat answers nothing itself


def test_maptelos_findings_are_as_of_now_and_old_advice_is_marked(
    studio: httpx2.Client, ai: tuple[FakeAi, str]
) -> None:
    _, url = ai
    turn_on(studio, url)
    assert studio.post("/api/build", json={"process": PROCESS}).status_code == 200
    studio.post(f"/api/processes/{PROCESS}/assistant/review", json={})
    before = settle(studio, PROCESS)["advice"]
    assert "Pytania bez odpowiedzi: 4" in [h["title"] for h in before["hints"]]
    assert before["stale"] is False
    time.sleep(2.1)  # past the second the review was kept with
    answered = {"answers": {"stop.this_product_has_no_active_price_version": "tak"}}
    assert studio.post(f"/api/processes/{PROCESS}/questions", json=answered).status_code == 200
    after = studio.get(f"/api/processes/{PROCESS}/assistant").json()["advice"]
    titles = [h["title"] for h in after["hints"]]
    assert "Pytania bez odpowiedzi: 3" in titles  # at once, without asking the AI
    assert "Reguła okna potwierdzenia" in titles  # the AI's advice is kept
    assert after["stale"] is True
