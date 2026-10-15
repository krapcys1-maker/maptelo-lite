"""The words above a reply's text are the header of the e-mail answered („to: Rochella
subject: Re: Aliquet.”, MiniWoB++ email-inbox-reply), not the field's name: the map named the
field and its input after one record's sender and subject, and the next record's reply had
another header. The field is named as the page calls it."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Browser

from maptelo.capture import Recorder, RecorderOptions
from maptelo.mapping import map_trace
from maptelo.trace import load_trace

pytestmark = pytest.mark.e2e
APP = "http://mail.test"
REPLY = """<!doctype html><meta charset="utf-8"><title>Reply</title>
<div id="reply">
  <div class="reply-header">
    <div class="reply-info"><label class="reply-to">to: </label><span>Rochella</span></div>
    <div class="reply-subject"><label class="reply-subj">subject: </label>Re: Aliquet.</div>
  </div>
  <div class="reply-body"><textarea id="reply-text"></textarea></div>
</div>
<button>Send</button>"""


def test_a_header_above_a_field_does_not_name_it(browser: Browser, tmp_path: Path) -> None:
    context = browser.new_context()
    page = context.new_page()
    page.route(
        f"{APP}/**",
        lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=REPLY),
    )
    recorder = Recorder(context, tmp_path / "rec", RecorderOptions(process="reply"))
    recorder.start(f"{APP}/", page)
    page.locator("#reply-text").fill("In.")
    recorder.pump()
    page.get_by_role("button", name="Send").click()
    recorder.pump()
    path = recorder.stop()
    context.close()
    trace = load_trace(path)
    fill = next(e for e in trace.events if e.type == "fill")
    assert fill.target is not None
    assert fill.target.beside is None
    assert list(map_trace(trace).model.inputs) == ["reply_text"]
