"""MiniERP in a real browser: the chaos must behave the way automation will meet it."""

from __future__ import annotations

import re

import httpx2
import pytest
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeout

pytestmark = pytest.mark.e2e
PLANNED = "2026-12-01"


def open_product(page: Page, customer: str = "C001", cpn: str = "48212-B") -> None:
    page.get_by_role("combobox", name="Customer").select_option(customer)
    page.get_by_role("textbox", name="CPN").fill(cpn)
    page.get_by_role("button", name="Search").click()
    expect(page.get_by_role("table", name="Price versions")).to_be_visible()


def price_on(api: httpx2.Client, day: str = PLANNED) -> str:
    response = api.get("/api/prices", params={"customer": "C001", "cpn": "48212-B", "on": day})
    price = response.json()["price"]
    assert isinstance(price, str)
    return price


def test_price_change_with_accessible_locators(page: Page, api: httpx2.Client) -> None:
    open_product(page)
    active_row = page.get_by_role("row").filter(has_text="Active")
    active_row.get_by_role("link", name="Select").click()
    page.get_by_role("textbox", name="Price").fill("135.00")
    page.get_by_role("textbox", name="Valid from").fill(PLANNED)
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("status")).to_have_text("Price saved (version V4).")
    assert price_on(api) == "135.00"


def test_large_change_asks_for_confirmation(page: Page, api: httpx2.Client) -> None:
    page.goto("/pricing/product/C001/48211-A")
    page.get_by_role("textbox", name="Price").fill("500.00")
    page.get_by_role("textbox", name="Valid from").fill(PLANNED)
    page.get_by_role("button", name="Save").click()
    dialog = page.get_by_role("dialog", name="Confirm price change")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Confirm").click()
    expect(page.get_by_role("status")).to_be_visible()


def test_session_popup_blocks_the_page_until_dismissed(page: Page, api: httpx2.Client) -> None:
    chaos = {"session_popup_rate": 1.0, "session_popup_delay_ms": [0, 0]}
    api.put("/api/testbed/chaos", json=chaos).raise_for_status()
    page.goto("/pricing")
    popup = page.get_by_role("dialog", name="Session expiring")
    expect(popup).to_be_visible()
    with pytest.raises(PlaywrightTimeout):
        page.get_by_role("button", name="Search").click(timeout=1_000)
    popup.get_by_role("button", name="Continue").click()
    expect(popup).to_be_hidden()
    page.get_by_role("button", name="Search").click(timeout=2_000)


def test_slow_page_shows_a_spinner_first(page: Page, api: httpx2.Client) -> None:
    api.put("/api/testbed/chaos", json={"slow_load_max_ms": 3000}).raise_for_status()
    for _ in range(10):  # find a page view that the seeded chaos made slow enough
        page.goto("/pricing")
        delay = int(page.locator("body").get_attribute("data-load-delay-ms") or 0)
        if delay >= 800:
            break
    else:
        pytest.fail("no page view was slow enough")
    expect(page.get_by_role("progressbar", name="Loading")).to_be_visible()
    expect(page.get_by_role("textbox", name="CPN")).to_be_visible()
    expect(page.get_by_role("progressbar", name="Loading")).to_be_hidden()


def test_layout_b_breaks_layout_a_locators(page: Page, api: httpx2.Client) -> None:
    api.put("/api/testbed/chaos", json={"layout": "b"}).raise_for_status()
    page.goto("/pricing")
    expect(page.get_by_role("textbox", name="Customer part no.")).to_be_visible()
    expect(page.get_by_role("textbox", name="CPN", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Find")).to_be_visible()


def test_lying_banner_is_only_caught_by_the_api(page: Page, api: httpx2.Client) -> None:
    api.put("/api/testbed/chaos", json={"lying_banner_rate": 1.0}).raise_for_status()
    open_product(page)
    page.get_by_role("row").filter(has_text="Active").get_by_role("link", name="Select").click()
    page.get_by_role("textbox", name="Price").fill("135.00")
    page.get_by_role("textbox", name="Valid from").fill(PLANNED)
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("status")).to_have_text(re.compile("Price saved"))
    assert price_on(api) == "129.90"
