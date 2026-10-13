"""A page that never ends loading (a news portal: adverts and trackers keep its "load" event
away) is recorded like any other: the recording starts once the page's document is there. An
address that cannot be reached says so in a sentence, and leaves no recording behind (13.10:
a recording on onet.pl failed after 30 s with Playwright's own message)."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import Browser

from maptelo.browser import AddressError
from maptelo.capture import Recorder, RecorderOptions
from maptelo.trace import load_trace

pytestmark = pytest.mark.e2e

PORTAL = """<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><title>Portal</title></head>
<body>
  <h1>Wiadomości</h1>
  <label for="q">Szukaj w serwisie</label> <input id="q" name="q">
  <button type="button">Szukaj</button>
  <img src="/advert" alt="" width="300" height="250">
</body></html>
"""


class Portal(BaseHTTPRequestHandler):
    """The page comes at once; its advert, as long as the test runs, never does."""

    server: PortalServer

    def do_GET(self) -> None:
        if self.path == "/advert":
            self.server.released.wait(60)
            return
        body = PORTAL.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


class PortalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Portal)
        self.released = threading.Event()


@pytest.fixture
def portal() -> Iterator[str]:
    server = PortalServer()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.released.set()
        server.shutdown()
        server.server_close()


def test_a_page_that_never_ends_loading_is_recorded(
    browser: Browser, portal: str, tmp_path: Path
) -> None:
    context = browser.new_context(viewport={"width": 1280, "height": 860})
    page = context.new_page()
    recorder = Recorder(context, tmp_path / "rec", RecorderOptions(process="portal"))
    began = time.monotonic()
    recorder.start(portal + "/", page)
    assert time.monotonic() - began < 10  # the page was waited for, not its advert
    page.get_by_label("Szukaj w serwisie").fill("kursy walut")
    page.get_by_role("button", name="Szukaj").click()
    recorder.pump()
    path = recorder.stop()
    context.close()
    done = [(e.type, e.target.name if e.target else None) for e in load_trace(path).actions()]
    assert done == [("navigate", None), ("fill", "Szukaj w serwisie"), ("click", "Szukaj")]


def test_an_address_that_cannot_be_reached_says_so_and_leaves_nothing(
    browser: Browser, tmp_path: Path
) -> None:
    with socket.socket() as probe:  # a port nothing listens on any more
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    address = f"http://127.0.0.1:{port}/"
    context = browser.new_context()
    folder = tmp_path / "rec"
    recorder = Recorder(context, folder, RecorderOptions(process="portal"))
    with pytest.raises(AddressError) as refused:
        recorder.start(address, context.new_page())
    context.close()
    assert str(refused.value) == f"cannot open {address}: net::ERR_CONNECTION_REFUSED"
    assert not folder.exists()  # not listed as a recording of the process
