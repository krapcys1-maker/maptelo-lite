"""Scripted demonstrations of the MiniERP price-change process.

A "person" (Playwright with human-like typing and pauses) performs each scenario, so the
Maptelo recorder captures realistic traces: the same process with different branches,
exceptions, interruptions and mistakes. The traces become test fixtures and, later, the
material from which rules are induced.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page

SCENARIO_TODAY = date(2026, 10, 7)
SCENARIO_SEED = 7
SCENARIO_PASSWORD = "demo-Secret-42"
PROCESS = "update_customer_price"
BUILD_ANSWERS: dict[str, object] = {
    "effect": {
        "description": "Od dnia valid_from obowiązuje nowa cena",
        "url": "/prices?customer={inputs.customer}&cpn={inputs.cpn}&on={inputs.valid_from}",
        "expect": {"price": "$inputs.price", "matches": 1},
        "api_base_url": "http://127.0.0.1:8701/api",
    },
    "stop.this_product_has_no_active_price_version": "tak",
    "why.confirm_price_change": "zmiana ceny o więcej niż 20%",
}
"""What a person answers when Maptelo builds the model from the recorded scenarios: how to
check the result, that "no active version" is a stop, why the confirmation happens."""

Outcome = Literal["saved", "not_found", "no_active"]


@dataclass(frozen=True)
class Scenario:
    id: str
    note: str
    customer: str
    cpn: str
    new_price: str | None = None
    """As the person types it (may use a decimal comma)."""
    valid_from: str | None = None
    outcome: Outcome = "saved"
    login: bool = False
    wrong_cpn_first: str | None = None
    rejected_date_first: str | None = None
    session_popup: bool = False
    several_versions: bool = False
    """The product shows several price versions, so the active one must be picked."""
    confirm: bool = False
    """The change is above 20%, so a confirmation dialog appears."""

    @property
    def expected_price(self) -> str | None:
        if self.new_price is None:
            return None
        return f"{Decimal(self.new_price.replace(',', '.')):.2f}"

    def expected_steps(self) -> list[tuple[str, str]]:
        """(action, element) of the steps a correct map of this recording contains."""
        steps = [
            ("navigate", "/pricing"),
            ("select_option", "Customer"),
            ("fill", "CPN"),
            ("click", "Search"),
        ]
        if self.outcome != "saved":
            return steps
        if self.several_versions:
            steps.append(("click", "Select"))
        steps += [("fill", "Price"), ("fill", "Valid from"), ("click", "Save")]
        if self.confirm:
            steps.append(("click", "Confirm"))
        return steps

    def expected_map(self) -> dict[str, Any]:
        """What a correct map of this one recording shows (ground truth for M2)."""
        saved = self.outcome == "saved"
        rejected = self.outcome == "not_found" or self.wrong_cpn_first or self.rejected_date_first
        return {
            "steps": [f"{action} {element}" for action, element in self.expected_steps()],
            "inputs": ["customer", "cpn", "price", "valid_from"] if saved else ["customer", "cpn"],
            "exceptions": 1 if rejected else 0,
            "interrupts": 1 if self.session_popup else 0,
            "preconditions": 1 if self.login else 0,
            "row_rule": {"Status": "Active"} if self.several_versions and saved else None,
        }

    def ground_truth(self) -> dict[str, Any]:
        data = {k: v for k, v in asdict(self).items() if v not in (None, False)}
        if self.expected_price:
            data["expected_price"] = self.expected_price
        data["expected_map"] = self.expected_map()
        return data


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "01-login-single-version",
        "Starts on the login page; one price version, so the form is preselected.",
        "C001", "48211-A", "320.00", "2026-12-01", login=True,
    ),
    Scenario(
        "02-several-versions",
        "Three versions: the active one has to be selected first.",
        "C001", "48212-B", "135.00", "2026-12-01", several_versions=True,
    ),
    Scenario(
        "03-four-versions",
        "Four versions including a planned one: select the active one.",
        "C002", "51002-D", "21.50", "2026-11-15", several_versions=True,
    ),
    Scenario(
        "04-active-and-planned",
        "An active and a planned version: select the active one.",
        "C001", "48213-C", "93.10", "2026-10-20", several_versions=True,
    ),
    Scenario(
        "05-large-change-confirmed",
        "Change above 20% (12.75 to 16.00): the confirmation dialog is accepted.",
        "C003", "70010-A", "16.00", "2026-12-01", confirm=True,
    ),
    Scenario(
        "06-product-not-found",
        "The CPN does not exist for this customer: the person stops.",
        "C002", "99999-Z", outcome="not_found",
    ),
    Scenario(
        "07-discontinued-product",
        "The product has no active price version: the person stops.",
        "C003", "70012-C", outcome="no_active",
    ),
    Scenario(
        "08-session-popup",
        "The 'Session expiring' popup appears on the product page; Continue is clicked.",
        "C001", "48211-A", "318.50", "2026-12-01", session_popup=True,
    ),
    Scenario(
        "09-past-date-corrected",
        "A date in the past is rejected first; the person corrects it.",
        "C002", "51001-A", "47.00", "2026-11-01", rejected_date_first="2026-10-01",
    ),
    Scenario(
        "10-wrong-cpn-then-right",
        "A mistyped CPN finds nothing; the right one is searched; price with a decimal comma.",
        "C003", "70011-B", "3,45", "2026-12-01", wrong_cpn_first="70011-V",
        several_versions=True,
    ),
)  # fmt: skip


def login(page: Page, base_url: str, password: str = SCENARIO_PASSWORD) -> None:
    page.goto(f"{base_url}/login")
    page.get_by_label("Username").fill("demo")
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url("**/pricing")


def perform(
    page: Page,
    scenario: Scenario,
    *,
    sync: Callable[[], object],
    set_chaos: Callable[[dict[str, Any]], object],
    password: str = SCENARIO_PASSWORD,
    rng: random.Random | None = None,
) -> None:
    """Act out a scenario. ``sync`` runs after every action (the recorder's pump)."""
    rng = rng or random.Random(scenario.id)

    def pause() -> None:
        page.wait_for_timeout(rng.randint(120, 380))

    def act(action: Callable[[], object]) -> None:
        action()
        sync()
        pause()

    def type_into(field: Locator, text: str) -> None:
        field.click(click_count=3)  # select what is there, like a person replacing a value
        page.keyboard.type(text, delay=rng.randint(30, 80))

    if scenario.login:
        act(lambda: type_into(page.get_by_label("Username"), "demo"))
        act(lambda: type_into(page.get_by_label("Password"), password))
        act(lambda: page.get_by_role("button", name="Sign in").click())

    act(lambda: page.get_by_role("combobox", name="Customer").select_option(scenario.customer))
    cpn = page.get_by_role("textbox", name="CPN")
    search = page.get_by_role("button", name="Search")
    if scenario.wrong_cpn_first:
        act(lambda: type_into(cpn, scenario.wrong_cpn_first or ""))
        act(search.click)
    act(lambda: type_into(cpn, scenario.cpn))
    if scenario.session_popup:
        set_chaos({"session_popup_rate": 1.0, "session_popup_delay_ms": [500, 700]})
    act(search.click)
    if scenario.session_popup:
        set_chaos({})
        dialog = page.get_by_role("dialog", name="Session expiring")
        dialog.wait_for()
        act(dialog.get_by_role("button", name="Continue").click)
    if scenario.outcome != "saved":
        return

    versions = page.get_by_role("table", name="Price versions").get_by_role("row")
    if versions.count() > 2:  # header row + more than one version
        active = page.get_by_role("row").filter(has_text="Active")
        act(active.get_by_role("link", name="Select").click)
    act(lambda: type_into(page.get_by_role("textbox", name="Price"), scenario.new_price or ""))
    valid_from = page.get_by_role("textbox", name="Valid from")
    save = page.get_by_role("button", name="Save")
    if scenario.rejected_date_first:
        act(lambda: type_into(valid_from, scenario.rejected_date_first or ""))
        act(save.click)
    act(lambda: type_into(valid_from, scenario.valid_from or ""))
    act(save.click)
    confirm = page.get_by_role("dialog", name="Confirm price change")
    if confirm.count():
        act(confirm.get_by_role("button", name="Confirm").click)
