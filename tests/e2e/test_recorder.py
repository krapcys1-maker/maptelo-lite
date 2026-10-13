"""The recorder against a live MiniERP, driven by the scripted person."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx2
import pytest
from playwright.sync_api import Browser

from maptelo.capture import Recorder, RecorderOptions, record_session
from maptelo.trace import Trace, load_trace
from minierp.scenarios import PROCESS, SCENARIO_PASSWORD, SCENARIOS, login, perform

pytestmark = pytest.mark.e2e
SCENARIO = {s.id: s for s in SCENARIOS}


def record(
    browser: Browser, live_server: str, api: httpx2.Client, scenario_id: str, out: Path
) -> Trace:
    scenario = SCENARIO[scenario_id]
    context = browser.new_context(viewport={"width": 1280, "height": 860})
    page = context.new_page()
    if not scenario.login:
        login(page, live_server)
    recorder = Recorder(context, out, RecorderOptions(process=PROCESS, note=scenario.note))
    start = "/login" if scenario.login else "/pricing"
    recorder.start(live_server + start, page)

    def set_chaos(chaos: dict[str, Any]) -> None:
        api.put("/api/testbed/chaos", json=chaos).raise_for_status()

    perform(page, scenario, sync=recorder.pump, set_chaos=set_chaos)
    path = recorder.stop()
    context.close()
    return load_trace(path)


def test_login_and_price_change_are_recorded(
    browser: Browser, live_server: str, api: httpx2.Client, tmp_path: Path
) -> None:
    trace = record(browser, live_server, api, "01-login-single-version", tmp_path / "rec")
    kinds = [(e.type, e.target.name if e.target else None) for e in trace.actions()]
    assert kinds == [
        ("navigate", None),
        ("fill", "Username"),
        ("fill", "Password"),
        ("click", "Sign in"),
        ("select", "Customer"),
        ("fill", "CPN"),
        ("click", "Search"),
        ("fill", "Price"),
        ("fill", "Valid from"),
        ("click", "Save"),
    ]
    # The password never reaches the disk: not in events, snapshots or anywhere else.
    for file in (tmp_path / "rec").rglob("*"):
        if file.suffix in (".jsonl", ".yaml", ".json"):
            assert SCENARIO_PASSWORD not in file.read_text(encoding="utf-8")
    # Every state has a screenshot on disk and an accessibility snapshot.
    for state in trace.states.values():
        assert state.screenshot is not None
        assert (tmp_path / "rec" / state.screenshot).is_file()
        assert "- " in state.aria
    save = trace.actions()[-1]
    after = trace.state(save.state_after)
    assert after is not None
    assert "Price saved" in after.aria


def test_the_picture_before_a_click_shows_what_was_typed_just_before(
    browser: Browser, live_server: str, api: httpx2.Client, tmp_path: Path
) -> None:
    """The date typed into „Valid from” reaches the trace only with the click on „Save” (the
    field is left then), so the screen before that click was read before the typing (the
    Lite film of 13.10: „Click “Save”” showed the form without the date). Once the typing
    stops the picture is taken again; the snapshot keeps what the screen held when read."""
    from PIL import Image

    context = browser.new_context(viewport={"width": 1280, "height": 860})
    page = context.new_page()
    login(page, live_server)
    out = tmp_path / "typed"
    recorder = Recorder(context, out, RecorderOptions(process=PROCESS))
    recorder.start(live_server + "/pricing", page)

    def typed(name: str, text: str) -> None:  # as the recording's loop sees it: the screen
        page.get_by_role("textbox", name=name).click(click_count=3)  # is read on entering the
        recorder.pump()  # field (the one left is written then), the typing comes after
        page.keyboard.type(text, delay=30)

    page.get_by_role("combobox", name="Customer").select_option("C001")
    recorder.pump()
    typed("CPN", "48211-A")
    page.get_by_role("button", name="Search").click()
    page.get_by_role("textbox", name="Price").wait_for()
    recorder.pump()
    typed("Price", "320.00")
    typed("Valid from", "2026-12-01")
    for _ in range(7):  # the person looks for „Save”; the loop goes on meanwhile
        page.wait_for_timeout(100)
        recorder.pump()
    page.get_by_role("button", name="Save").click()
    page.get_by_text("Price saved").wait_for()
    recorder.pump()
    trace = load_trace(recorder.stop())
    context.close()

    date = next(a for a in trace.actions() if a.target and a.target.name == "Valid from")
    save = trace.actions()[-1]
    assert save.target is not None
    assert save.target.name == "Save"
    before = trace.state(save.state_before)
    assert before is not None
    assert before.screenshot is not None
    assert 'textbox "Valid from": 2026-12-01' not in before.aria  # read before the typing
    assert date.target is not None
    assert date.target.bbox is not None
    x, y, width, height = date.target.bbox
    field = Image.open(out / before.screenshot).convert("L")
    field = field.crop((round(x) + 4, round(y) + 4, round(x + width) - 4, round(y + height) - 4))
    ink = sum(1 for level in field.getdata() if level < 90)  # typed text, not the grey hint
    assert ink > 30, "the picture before „Save” shows the date field empty"


def test_row_choice_and_popup_are_captured(
    browser: Browser, live_server: str, api: httpx2.Client, tmp_path: Path
) -> None:
    trace = record(browser, live_server, api, "02-several-versions", tmp_path / "rows")
    choose = next(a for a in trace.actions() if a.target and a.target.name == "Select")
    assert choose.target is not None
    assert choose.target.row is not None
    assert choose.target.row.table == "Price versions"
    assert choose.target.row.cells["Status"] == "Active"
    assert choose.target.candidates[0].describe() == 'role=link name="Select"'

    popup = record(browser, live_server, api, "08-session-popup", tmp_path / "popup")
    appeared = [e for e in popup.events if e.type == "appeared" and e.target]
    assert any(e.target and e.target.name == "Session expiring" for e in appeared)
    continue_click = next(a for a in popup.actions() if a.target and a.target.name == "Continue")
    assert continue_click.target is not None
    assert continue_click.target.dialog == "Session expiring"


def test_events_from_other_sites_are_ignored(
    browser: Browser, live_server: str, tmp_path: Path
) -> None:
    context = browser.new_context()
    page = context.new_page()
    login(page, live_server)
    recorder = Recorder(context, tmp_path / "scoped", RecorderOptions(screenshots=False))
    recorder.start(live_server + "/pricing", page)
    page.goto("data:text/html,<button>Elsewhere</button>")
    page.get_by_role("button", name="Elsewhere").click()
    recorder.pump()
    trace = load_trace(recorder.stop())
    context.close()
    assert all(not (e.target and e.target.name == "Elsewhere") for e in trace.events)


def run_session(url: str, out: Path) -> Path:
    # record_session starts its own Playwright, so it runs in a separate thread here.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(record_session, url, out, None, headless=True, timeout_s=2)
        return future.result(timeout=60)


def test_interactive_session_ends_on_timeout(live_server: str, tmp_path: Path) -> None:
    trace = load_trace(run_session(live_server + "/login", tmp_path / "session"))
    assert trace.end is not None
    assert trace.end.reason == "timeout"
    assert [e.type for e in trace.actions()] == ["navigate"]
    assert len(trace.states) >= 1


def test_form_fields_are_recorded_with_the_name_they_are_sent_under(
    browser: Browser, live_server: str, api: httpx2.Client, tmp_path: Path
) -> None:
    """The name a form sends a value under survives an update that changes the words: the
    recorder keeps it, the ladder gets a field rung, and an expectation that a field appears
    accepts either its words or its name."""
    from maptelo.mapping import map_trace
    from maptelo.model.schema import Locator

    trace = record(browser, live_server, api, "02-several-versions", tmp_path / "rec")
    fields = {
        e.target.name: e.target.field for e in trace.actions() if e.target and e.type == "fill"
    }
    assert fields == {"CPN": "cpn", "Price": "price", "Valid from": "valid_from"}
    model = map_trace(trace).model
    price = next(s for s in model.steps if s.target and s.target[0].name == "Price")
    assert {"field": "price"} in [r.model_dump(exclude_none=True) for r in price.target or []]
    # choosing the row shows the form on the same page: the expectation is the field appearing
    chosen = model.steps[model.steps.index(price) - 1]
    assert chosen.action == "click"
    assert chosen.within is not None  # the only table on the screen, the only link in the row
    assert chosen.within.table[1:] == [Locator(role="table")]
    assert chosen.target is not None
    assert chosen.target[-1] == Locator(role="link")
    assert chosen.expect is not None
    shapes = [p.model_dump(exclude_none=True) for p in chosen.expect.any_ or []]
    assert shapes == [
        {"visible": {"role": "textbox", "name": "Price"}},
        {"visible": {"field": "price"}},
    ], chosen.expect


def test_a_button_that_sends_a_form_is_recorded_with_what_the_form_sends(
    browser: Browser, live_server: str, api: httpx2.Client, tmp_path: Path
) -> None:
    """Search sends the customer, Save the price, the dialog's Confirm what only its own form
    sends: a word-free way to find each of them after an update renames it."""
    trace = record(browser, live_server, api, "05-large-change-confirmed", tmp_path / "rec")
    sends = {
        e.target.name: e.target.submits for e in trace.actions() if e.type == "click" and e.target
    }
    assert sends == {"Search": "customer", "Save": "price", "Confirm": "confirmed"}
