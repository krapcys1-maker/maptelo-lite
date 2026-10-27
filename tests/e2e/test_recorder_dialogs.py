"""A browser dialog during a recording is the person's to answer: the recorder leaves it open
(Playwright would dismiss it at once), and the answer the person gave is what is recorded.
A start address that hands the person over to another one keeps their steps recorded."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Dialog

from maptelo.capture.web import Recorder, RecorderOptions

pytestmark = pytest.mark.e2e
APP = "http://dialog.test"
PAGE = """<title>Faktura</title><button onclick="
  document.title = confirm('Zaksięgować fakturę?') ? 'tak' : 'nie'">Zaksięguj</button>"""
HTML = "text/html; charset=utf-8"


def events(trace: Path, kind: str) -> list[dict[str, Any]]:
    lines = [json.loads(x) for x in trace.read_text("utf-8").splitlines()]
    return [x for x in lines if x["kind"] == "event" and x["type"] == kind]


def test_a_confirm_waits_for_the_person_and_their_answer_is_recorded(
    browser: Browser, tmp_path: Path
) -> None:
    context = browser.new_context()
    context.route(f"{APP}/**", lambda route: route.fulfill(content_type=HTML, body=PAGE))
    listened: list[str] = []
    on = context.on
    context.on = lambda event, handler: listened.append(event) or on(event, handler)  # type: ignore[method-assign,func-returns-value]
    recorder = Recorder(context, tmp_path / "rec", RecorderOptions(screenshots=False))
    context.on = on  # type: ignore[method-assign]
    assert "dialog" in listened  # without a listener Playwright says "Cancel" at once
    page = recorder.start(f"{APP}/")
    waiting: list[Dialog] = []
    context.on("dialog", lambda dialog: waiting.append(dialog))  # the person: no answer yet
    page.evaluate("() => setTimeout(() => document.querySelector('button').click(), 10)")
    page.wait_for_timeout(500)
    assert len(waiting) == 1  # still open: nobody answered it for the person
    waiting[0].accept()  # the person presses OK
    page.wait_for_function("document.title === 'tak'")
    recorder.pump()
    dialogs = [x["dialog"] for x in events(recorder.stop(), "dialog")]
    assert dialogs == [{"kind": "confirm", "message": "Zaksięgować fakturę?", "accepted": True}]
    context.close()


def _server(answer: Any) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            answer(self)

        def log_message(self, *_: object) -> None: ...

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


@pytest.fixture
def application() -> Iterator[str]:
    def form(handler: BaseHTTPRequestHandler) -> None:
        body = b"<label>Numer <input></label>"
        handler.send_response(200)
        handler.send_header("Content-Type", HTML)
        handler.end_headers()
        handler.wfile.write(body)

    yield from _server(form)


@pytest.fixture
def portal(application: str) -> Iterator[str]:
    def hand_over(handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(302)
        handler.send_header("Location", f"{application}/start")
        handler.end_headers()

    yield from _server(hand_over)


def test_steps_on_the_address_a_start_page_hands_over_to_are_recorded(
    browser: Browser, tmp_path: Path, portal: str
) -> None:
    context = browser.new_context()
    recorder = Recorder(context, tmp_path / "rec", RecorderOptions(screenshots=False))
    page = recorder.start(f"{portal}/")  # another port: another origin
    page.get_by_label("Numer").fill("FV/7")
    page.get_by_label("Numer").press("Tab")
    recorder.pump()
    assert [x["value"] for x in events(recorder.stop(), "fill")] == ["FV/7"]
    context.close()
