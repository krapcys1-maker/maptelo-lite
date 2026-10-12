"""Which screen an address shows, for classic pages and single-page applications."""

from __future__ import annotations

import pytest

from maptelo.model.urls import fill_from, origin, screen_template, url_matches

ODOO_LIST = (
    "http://127.0.0.1:8069/web#action=175&model=product.pricelist&view_type=list&menu_id=181"
)
ODOO_FORM = (
    "http://127.0.0.1:8069/web#id=2&menu_id=181&action=175&model=product.pricelist&view_type=form"
)


def test_paths_and_fragments_become_screens() -> None:
    assert screen_template("http://h/pricing/product/C001/48212-B") == "/pricing/product/*/*"
    assert screen_template(ODOO_LIST) == "/web#model=product.pricelist&view_type=list"
    assert screen_template(ODOO_FORM) == "/web#model=product.pricelist&view_type=form"
    assert screen_template("http://h/app#/orders/12") == "/app#/orders/*"
    assert screen_template("http://h/pricing?customer=C001") == "/pricing"


@pytest.mark.parametrize(
    ("url", "pattern", "matches"),
    [
        ("http://h/pricing/product/C001/X-1", "/pricing/product/*", True),
        ("http://h/pricing", "/pricing/product/*", False),
        (ODOO_LIST, "/web#model=product.pricelist&view_type=list", True),
        (ODOO_FORM, "/web#view_type=form&model=product.pricelist", True),  # any order
        (ODOO_FORM, "/web#model=product.pricelist&view_type=list", False),
        (ODOO_LIST, "/web", True),  # a pattern without # ignores the fragment
        ("http://h/web#model=res.partner&view_type=form", "/web#model=product.*", False),
        ("http://h/app#/orders/12", "/app#/orders/*", True),
    ],
)
def test_matching(url: str, pattern: str, matches: bool) -> None:
    assert url_matches(url, pattern) is matches


def test_an_address_that_names_a_record_takes_it_from_the_data() -> None:
    """``/zamowienia/2`` for every row of the sheet would put each row's work into order 2:
    a part that names a record is the value from the data that holds it, or unexplained."""
    names = {"ZS/2026/0002": "inputs.numer", "3123435783": "inputs.nip"}
    assert fill_from("/zamowienia/ZS%2F2026%2F0002", names) == ("/zamowienia/{inputs.numer}", [])
    assert fill_from("http://wl.test/szukaj?nip=3123435783&action=search", names) == (
        "http://wl.test/szukaj?nip={inputs.nip}&action=search",
        [],
    )
    assert fill_from("http://erp.test/zamowienia/2", names) == (
        "http://erp.test/zamowienia/2",
        ["2"],
    )
    assert fill_from(ODOO_FORM, {}) == (ODOO_FORM, ["2", "181", "175"])


def test_an_address_of_a_screen_names_no_record() -> None:
    """Words name a screen; a number may be a menu's as well as a record's, so it counts as a
    record's until several recordings show the same address (induction)."""
    for address in ("/dostawcy/nowy", "/?_task=mail&_mbox=INBOX", "/web#view_type=list"):
        assert fill_from(address, {})[1] == [], address
    assert origin("https://erp.example.com:8443/orders/2?x=1") == "https://erp.example.com:8443"
