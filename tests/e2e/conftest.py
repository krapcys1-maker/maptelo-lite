from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from minierp import Settings
from minierp.scenarios import SCENARIO_PASSWORD, SCENARIO_SEED, SCENARIO_TODAY, login
from minierp.server import running

HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Every test here is an end-to-end one (a browser, the test application), marked or
    not: ``-m "not e2e"`` never needs a browser."""
    for item in items:
        if HERE in item.path.resolve().parents:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(scope="session")
def live_server() -> Iterator[str]:
    settings = Settings(seed=SCENARIO_SEED, today=SCENARIO_TODAY, password=SCENARIO_PASSWORD)
    with running(settings) as base_url:
        yield base_url


@pytest.fixture
def api(live_server: str) -> Iterator[httpx2.Client]:
    """Testbed control channel; every test starts from fresh data and no chaos."""
    with httpx2.Client(base_url=live_server) as client:
        client.post("/api/testbed/reset").raise_for_status()
        client.put("/api/testbed/chaos", json={}).raise_for_status()
        yield client


@pytest.fixture(scope="session")
def playwright() -> Iterator[Playwright]:
    """One Playwright for the whole session: the sync API cannot run two in one thread."""
    with sync_playwright() as started:
        yield started


@pytest.fixture(scope="session")
def browser(playwright: Playwright) -> Iterator[Browser]:
    launched = playwright.chromium.launch()
    yield launched
    launched.close()


@pytest.fixture
def page(browser: Browser, live_server: str, api: httpx2.Client) -> Iterator[Page]:
    """A signed-in page on MiniERP."""
    context = browser.new_context(base_url=live_server, viewport={"width": 1280, "height": 860})
    context.set_default_timeout(10_000)
    signed_in = context.new_page()
    login(signed_in, live_server)
    yield signed_in
    context.close()
