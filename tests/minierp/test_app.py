from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import date

import httpx2
import pytest
from fastapi.testclient import TestClient

from minierp import Chaos, Settings, create_app
from minierp.app import Testbed

TODAY = date(2026, 10, 7)
PLANNED = "2026-12-01"  # first day of the month after next
ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_client() -> ClientFactory:
    def make(chaos: Chaos | None = None, seed: int = 7, login: bool = True) -> TestClient:
        app = create_app(Settings(seed=seed, today=TODAY, chaos=chaos or Chaos()))
        client = TestClient(app, follow_redirects=False)
        if login:
            response = client.post("/login", data={"username": "demo", "password": "demo"})
            assert response.status_code == 303
        return client

    return make


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


def state_of(client: TestClient) -> Testbed:
    tb = client.app.state.testbed  # type: ignore[attr-defined]
    assert isinstance(tb, Testbed)
    return tb


def active_version_id(client: TestClient, customer: str, cpn: str) -> int:
    tb = state_of(client)
    product = tb.store.product(customer, cpn)
    assert product is not None
    return next(r.version.id for r in tb.store.rows(product, TODAY) if r.status == "Active")


def save(
    client: TestClient, price: str, valid_from: str = PLANNED, **extra: str
) -> httpx2.Response:
    data = {
        "base_version": str(active_version_id(client, "C001", "48212-B")),
        "price": price,
        "valid_from": valid_from,
        **extra,
    }
    return client.post("/pricing/product/C001/48212-B/price", data=data)


def api_price(client: TestClient, on: str = PLANNED) -> dict[str, object]:
    response = client.get("/api/prices", params={"customer": "C001", "cpn": "48212-B", "on": on})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)
    return body


# --- Sign-in ---------------------------------------------------------------------------


def test_pages_require_login(make_client: ClientFactory) -> None:
    response = make_client(login=False).get("/pricing")
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/pricing"


def test_wrong_password_is_rejected(make_client: ClientFactory) -> None:
    client = make_client(login=False)
    response = client.post("/login", data={"username": "demo", "password": "nope"})
    assert response.status_code == 401
    assert "Invalid username or password." in response.text


def test_login_does_not_redirect_off_site(make_client: ClientFactory) -> None:
    client = make_client(login=False)
    data = {"username": "demo", "password": "demo", "next": "//evil.example"}
    assert client.post("/login", data=data).headers["location"] == "/pricing"


# --- Search and product page -----------------------------------------------------------


def test_search_finds_product_case_insensitively(client: TestClient) -> None:
    response = client.get("/pricing/search", params={"customer": "C001", "cpn": " 48212-b "})
    assert response.status_code == 303
    assert response.headers["location"] == "/pricing/product/C001/48212-B"


def test_search_reports_unknown_cpn(client: TestClient) -> None:
    response = client.get("/pricing/search", params={"customer": "C001", "cpn": "99999-Z"})
    assert 'role="alert"' in response.text
    assert "No product found for CPN 99999-Z." in response.text


def test_single_version_is_preselected(client: TestClient) -> None:
    page = client.get("/pricing/product/C001/48211-A").text
    assert 'name="base_version"' in page
    assert "Current price" in page


def test_several_versions_require_choosing_the_active_one(client: TestClient) -> None:
    page = client.get("/pricing/product/C001/48212-B").text
    assert 'name="base_version"' not in page
    assert "Select the active one" in page
    assert page.count(">Select</a>") == 3  # every row offers it, only one may be used

    tb = state_of(client)
    product = tb.store.product("C001", "48212-B")
    assert product is not None
    expired = next(r.version.id for r in tb.store.rows(product, TODAY) if r.status == "Expired")
    wrong = client.get(f"/pricing/product/C001/48212-B?version={expired}").text
    assert "Only the active price version can be changed." in wrong

    active = active_version_id(client, "C001", "48212-B")
    chosen = client.get(f"/pricing/product/C001/48212-B?version={active}").text
    assert 'name="base_version"' in chosen


def test_discontinued_product_has_no_active_version(client: TestClient) -> None:
    page = client.get("/pricing/product/C003/70012-C").text
    assert "no active price version" in page
    assert 'name="base_version"' not in page


# --- Saving ----------------------------------------------------------------------------


def test_save_creates_a_version_that_the_api_confirms(client: TestClient) -> None:
    response = save(client, "135.00")
    assert response.status_code == 303
    location = response.headers["location"]
    assert location == "/pricing/product/C001/48212-B?saved=V4"
    page = client.get(location).text
    assert 'role="status"' in page
    assert "Price saved (version V4)." in page
    assert api_price(client)["price"] == "135.00"
    assert api_price(client)["matches"] == 1
    assert api_price(client, on="2026-11-30")["price"] == "129.90"


def test_decimal_comma_is_accepted(client: TestClient) -> None:
    save(client, "135,50")
    assert api_price(client)["price"] == "135.50"


@pytest.mark.parametrize(
    ("price", "valid_from", "message"),
    [
        ("abc", PLANNED, "Price must be a positive amount"),
        ("0", PLANNED, "Price must be a positive amount"),
        ("12.345", PLANNED, "Price must be a positive amount"),
        ("135.00", "01.12.2026", "format YYYY-MM-DD"),
        ("135.00", "2026-10-01", "cannot be in the past"),
    ],
)
def test_invalid_input_is_rejected(
    client: TestClient, price: str, valid_from: str, message: str
) -> None:
    response = save(client, price, valid_from)
    assert response.status_code == 422
    assert message in response.text
    assert api_price(client)["price"] == "129.90"


def test_large_change_needs_confirmation(client: TestClient) -> None:
    response = save(client, "200.00")
    assert response.status_code == 200
    assert 'role="dialog"' in response.text
    assert "Confirm price change" in response.text
    assert "differs by 54.0%" in response.text
    assert api_price(client)["price"] == "129.90"

    confirmed = save(client, "200.00", confirmed="1")
    assert confirmed.status_code == 303
    assert api_price(client)["price"] == "200.00"


def test_lying_banner_reports_success_without_saving(make_client: ClientFactory) -> None:
    client = make_client(Chaos(lying_banner_rate=1.0))
    location = save(client, "135.00").headers["location"]
    assert location.endswith("?saved=V4")
    assert "Price saved (version V4)." in client.get(location).text
    assert api_price(client)["price"] == "129.90"  # the system of record disagrees
    assert [e["type"] for e in state_of(client).events] == ["lying_banner"]


def test_double_submit_creates_a_duplicate(client: TestClient) -> None:
    save(client, "135.00")
    save(client, "135.00")
    versions = client.get("/api/products/C001/48212-B/versions").json()
    assert [v["valid_from"] for v in versions].count(PLANNED) == 2
    assert api_price(client)["matches"] == 2


# --- Chaos -----------------------------------------------------------------------------


def test_layout_b_renames_everything(make_client: ClientFactory) -> None:
    client = make_client(Chaos(layout="b"))
    search = client.get("/pricing").text
    assert "Customer part no." in search
    assert ">CPN<" not in search
    assert "data-testid" not in search
    product = client.get("/pricing/product/C001/48211-A").text
    assert "Pricing history" in product
    assert "Apply changes" in product
    assert product.index('name="base_version"') < product.index("<table")  # form moved up


def test_session_popup_is_decided_per_page_view(make_client: ClientFactory) -> None:
    always = make_client(Chaos(session_popup_rate=1.0, session_popup_delay_ms=(50, 50)))
    assert 'data-session-popup-ms="50"' in always.get("/pricing").text
    assert state_of(always).events[-1]["type"] == "session_popup"
    never = make_client(Chaos(session_popup_rate=0.0))
    assert "data-session-popup-ms" not in never.get("/pricing").text


def test_slow_loading_hides_the_page_behind_a_spinner(make_client: ClientFactory) -> None:
    client = make_client(Chaos(slow_load_max_ms=2000))
    pages = [client.get("/pricing").text for _ in range(5)]
    slow = [p for p in pages if "data-load-delay-ms" in p]
    assert slow, "with up to 2 s of delay at least one of five pages should be slow"
    assert all('<main id="main" hidden>' in p for p in slow)


def test_chaos_is_deterministic_for_a_seed(make_client: ClientFactory) -> None:
    def popups(seed: int) -> list[bool]:
        client = make_client(Chaos(session_popup_rate=0.5), seed=seed)
        return ["data-session-popup-ms" in client.get("/pricing").text for _ in range(12)]

    assert popups(11) == popups(11)


def test_a_save_error_stores_nothing(make_client: ClientFactory) -> None:
    client = make_client(Chaos(save_error_rate=1.0))
    response = save(client, "135.00")
    assert response.status_code == 500
    assert "500 Internal Server Error" in response.text
    assert api_price(client)["price"] == "129.90"
    assert [e["type"] for e in state_of(client).events] == ["save_error"]


def test_a_lost_answer_comes_after_the_price_is_stored(make_client: ClientFactory) -> None:
    client = make_client(Chaos(lost_response_rate=1.0))
    response = save(client, "135.00")
    assert response.status_code == 502
    assert "502 Bad Gateway" in response.text
    assert api_price(client)["price"] == "135.00"  # saved, though the screen says otherwise
    assert [e["type"] for e in state_of(client).events] == ["price_saved", "lost_response"]


def test_a_slow_save_waits_before_answering(make_client: ClientFactory) -> None:
    client = make_client(Chaos(slow_save_max_ms=300), seed=3)
    started = time.monotonic()
    assert save(client, "135.00").status_code == 303
    slow = [e for e in state_of(client).events if e["type"] == "slow_save"]
    if slow:  # the seed may draw 0 ms
        assert time.monotonic() - started >= slow[0]["delay_ms"] / 1000
        assert slow[0]["delay_ms"] <= 300
    assert api_price(client)["price"] == "135.00"


def test_the_read_api_can_lag_behind_a_save(make_client: ClientFactory) -> None:
    client = make_client(Chaos(read_lag_ms=400))
    save(client, "135.00")
    assert api_price(client)["price"] == "129.90"  # not seen yet
    versions = client.get("/api/products/C001/48212-B/versions").json()
    assert "135.00" in [v["price"] for v in versions]  # the record itself is there
    time.sleep(0.45)
    assert api_price(client)["price"] == "135.00"


def test_the_read_api_can_fail(make_client: ClientFactory) -> None:
    client = make_client(Chaos(read_error_rate=1.0))
    response = client.get(
        "/api/prices", params={"customer": "C001", "cpn": "48212-B", "on": PLANNED}
    )
    assert response.status_code == 503
    assert client.get("/api/products/C001/48212-B/versions").status_code == 200
    assert state_of(client).events[-1]["type"] == "read_error"


def test_trouble_that_is_off_does_not_shift_a_seed(make_client: ClientFactory) -> None:
    def popups(saves: bool) -> list[bool]:
        client = make_client(Chaos(session_popup_rate=0.5), seed=11)
        seen = []
        for i in range(8):
            seen.append("data-session-popup-ms" in client.get("/pricing").text)
            if saves and i == 3:
                save(client, "135.00")
        return seen

    assert popups(saves=True) == popups(saves=False)


def test_chaos_can_be_changed_at_runtime(client: TestClient) -> None:
    response = client.put("/api/testbed/chaos", json={"layout": "b"})
    assert response.status_code == 200
    assert "Customer part no." in client.get("/pricing").text


# --- API -------------------------------------------------------------------------------


def test_api_errors(client: TestClient) -> None:
    unknown = client.get(
        "/api/prices", params={"customer": "C001", "cpn": "00000-X", "on": PLANNED}
    )
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "product not found"}
    too_early = client.get(
        "/api/prices", params={"customer": "C001", "cpn": "48212-B", "on": "2000-01-01"}
    )
    assert too_early.status_code == 404


def test_reset_restores_the_seed(client: TestClient) -> None:
    save(client, "135.00")
    assert client.post("/api/testbed/reset").json() == {"status": "reset"}
    assert len(client.get("/api/products/C001/48212-B/versions").json()) == 3
    assert state_of(client).events == []


def test_health_reports_configuration(client: TestClient) -> None:
    assert client.get("/api/health").json() == {
        "status": "ok",
        "layout": "a",
        "drift": [],
        "seed": 7,
        "today": TODAY.isoformat(),
    }


def test_versions_show_computed_end_dates(client: TestClient) -> None:
    versions = client.get("/api/products/C001/48213-C/versions").json()
    assert [v["status"] for v in versions] == ["Active", "Planned"]
    assert versions[0]["valid_to"] == "2026-11-30"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", versions[1]["valid_from"])
