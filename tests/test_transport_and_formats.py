"""Keys stay with the service they are for, the computer's policy is the one that holds, and a
file of a newer Maptelo is refused with a sentence that says what to do."""

from __future__ import annotations

import threading
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from maptelo.model import ModelLoadError, parse_model
from maptelo.net import open_url
from maptelo.policy import policy_path
from maptelo.trace import TraceError, load_trace


class _Seen(BaseHTTPRequestHandler):
    heard: list[dict[str, str]]
    goes_to: str = ""

    def do_GET(self) -> None:
        type(self).heard.append({k.lower(): v for k, v in self.headers.items()})
        if self.goes_to:
            self.send_response(302)
            self.send_header("Location", self.goes_to)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args: object) -> None:
        pass


def _serve(handler: type[_Seen]) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


@pytest.fixture
def other() -> Iterator[tuple[type[_Seen], str]]:
    handler = type("Other", (_Seen,), {"heard": []})
    for base in _serve(handler):
        yield handler, base


def test_a_key_does_not_follow_a_redirect_to_another_host(
    other: tuple[type[_Seen], str],
) -> None:
    elsewhere, base = other
    target = base.replace("127.0.0.1", "localhost") + "/data"  # another host: same machine
    asked = type("Asked", (_Seen,), {"heard": [], "goes_to": target})
    for start in _serve(asked):
        request = urllib.request.Request(
            f"{start}/api", headers={"Authorization": "Bearer klucz", "X-Api-Key": "k"}
        )
        with open_url(request, timeout=5) as response:
            assert response.status == 200
    assert asked.heard[0]["authorization"] == "Bearer klucz"  # to the service asked
    assert "authorization" not in elsewhere.heard[0]  # not to the one it sent Maptelo to
    assert "x-api-key" not in elsewhere.heard[0]


def test_the_computer_s_policy_comes_before_a_person_s_variable(tmp_path: Path) -> None:
    machine = tmp_path / "ProgramData" / "Maptelo" / "policy.yaml"
    machine.parent.mkdir(parents=True)
    machine.write_text("ai:\n  allowed: false\n", encoding="utf-8")
    own = tmp_path / "moja.yaml"
    env = {"ProgramData": str(tmp_path / "ProgramData"), "MAPTELO_POLICY": str(own)}
    assert policy_path(env) == machine
    machine.unlink()
    assert policy_path(env) == own  # where the computer has none, the variable names one


MODEL = """schema_version: "{version}"
id: ceny
version: 1
title: Ceny
application: {{name: MiniERP, base_url: "http://127.0.0.1:1"}}
steps:
  - {{id: open, intent: Otwórz, action: navigate, value: /}}
"""


def test_a_model_of_a_newer_maptelo_says_so() -> None:
    assert parse_model(MODEL.format(version="0.1")).id == "ceny"
    with pytest.raises(ModelLoadError, match=r"made by a newer Maptelo .*0\.2.*update Maptelo"):
        parse_model(MODEL.format(version="0.2"))


def test_a_recording_of_a_newer_maptelo_says_so(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    path.write_text(
        '{"kind": "header", "format": "maptelo-trace/0.3", "recording_id": "r1",'
        ' "started_at": "2026-10-21T08:00:00Z", "start_url": "http://app/", "extra": 1}\n',
        encoding="utf-8",
    )
    with pytest.raises(TraceError, match="made by a newer Maptelo"):
        load_trace(path)
