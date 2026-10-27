"""A password the person shows with the eye button (the field becomes type=text) stays a
secret: it is neither the fill's value nor in any screen the recording keeps."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Browser

from maptelo.capture.web import Recorder, RecorderOptions

pytestmark = pytest.mark.e2e
APP = "http://login.test"
PAGE = """<title>Logowanie</title><label>Hasło <input id=p type=password></label>
<button onmousedown="event.preventDefault()" onclick="p.type = p.type === 'password' ? 'text' : 'password'">Pokaż</button>
<label>Uwagi <input id=n></label>"""  # noqa: E501
SECRET = "Tajne!2026"


def test_a_shown_password_stays_secret(browser: Browser, tmp_path: Path) -> None:
    context = browser.new_context()
    context.route(
        f"{APP}/**", lambda r: r.fulfill(content_type="text/html; charset=utf-8", body=PAGE)
    )
    recorder = Recorder(context, tmp_path / "rec", RecorderOptions(screenshots=False))
    page = recorder.start(f"{APP}/")
    page.locator("#p").fill(SECRET)
    page.get_by_role("button", name="Pokaż").click()  # keeps the focus: no flush before
    recorder.pump()
    page.locator("#n").click()  # leaves the field, now shown as text
    page.locator("#n").fill("pilne")
    page.locator("#n").press("Tab")
    recorder.pump()
    text = recorder.stop().read_text(encoding="utf-8")
    assert SECRET not in text
    fills = [json.loads(x) for x in text.splitlines() if '"type":"fill"' in x.replace(" ", "")]
    assert [(f.get("secret", False), f.get("value")) for f in fills] == [
        (True, None),
        (False, "pilne"),
    ]
    context.close()
