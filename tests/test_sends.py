"""What sends data to an application (may save) and what only reads."""

from __future__ import annotations

import pytest

from maptelo.sends import describe, sends_data

APP = "http://erp.test"


@pytest.mark.parametrize(
    ("method", "path", "saves"),
    [
        ("GET", "/pricing/search?cpn=1", False),
        ("HEAD", "/", False),
        ("POST", "/pricing/product/C001/48211-A/price", True),
        ("PUT", "/api/orders/12", True),
        ("DELETE", "/api/orders/12", True),
        ("post", "/faktury/12/ksiegowanie", True),  # "Księguj": a save whatever the button says
        ("POST", "/session/keepalive", False),  # keeping the session alive
        ("POST", "/bus/im_status", False),
        ("POST", "/web/dataset/call_kw/product.pricelist/web_search_read", False),  # Odoo reads
        ("POST", "/web/dataset/call_kw/product.pricelist.item/onchange", False),
        ("POST", "/web/dataset/call_kw/product.pricelist/web_save", True),  # Odoo saves
        ("POST", "/web/dataset/call_button/sale.order/action_confirm", True),
        ("POST", "/web/dataset/call_kw/res.partner/some_new_method", True),  # in doubt: a save
        ("POST", "/web/action/load", False),
        ("POST", "/mail/thread/messages", False),  # Odoo's chatter beside a record (seen live)
    ],
)
def test_what_may_save(method: str, path: str, saves: bool) -> None:
    assert sends_data(method, APP + path) is saves


def test_what_was_sent_is_said_without_its_content() -> None:
    assert describe("post", APP + "/orders/12/invoice?x=1") == "POST /orders/12/invoice"
    assert describe("POST", APP + "/orders/12/invoice", private=True) == "POST /orders/*/invoice"
