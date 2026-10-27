"""Maptelo's own HTTPS: checked by the operating system, as in the browser, and through the
proxy Windows or the environment names."""

from __future__ import annotations

import ssl
import urllib.request
from typing import Any

import pytest
import truststore

from maptelo import net
from maptelo.checks import Check, summary_line


def test_https_is_checked_by_the_system() -> None:
    assert net.SYSTEM_TRUST
    context = net.https_context()
    assert isinstance(context, truststore.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert net.https_context() is context  # one for every connection


def test_every_connection_carries_the_context(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class Opener:
        def open(self, request: object, timeout: float) -> str:
            seen.update(request=request, timeout=timeout)
            return "answer"

    monkeypatch.setattr(net, "_opener", Opener)
    assert net.open_url("https://erp.example/api", 7) == "answer"
    assert seen == {"request": "https://erp.example/api", "timeout": 7}
    monkeypatch.undo()
    handlers = net._opener().handlers
    https = [h for h in handlers if isinstance(h, urllib.request.HTTPSHandler)]
    assert [h._context for h in https] == [net.https_context()]  # the system's trust


def test_a_summary_in_both_languages() -> None:
    fine = [Check("ok", "browsers", "Edge")]
    broken = [*fine, Check("FAIL", "loopback", "x"), Check("FAIL", "loopback", "y")]
    assert summary_line(fine) == "ready: all checks passed"
    assert summary_line(fine, "pl") == "gotowe: wszystkie sprawdzenia zakończone powodzeniem"
    assert summary_line(broken, "pl") == "niegotowe: loopback"
