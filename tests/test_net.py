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

    def urlopen(request: object, timeout: float, context: ssl.SSLContext) -> str:
        seen.update(request=request, timeout=timeout, context=context)
        return "answer"

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert net.open_url("https://erp.example/api", 7) == "answer"
    assert seen == {
        "request": "https://erp.example/api",
        "timeout": 7,
        "context": net.https_context(),
    }


def test_a_summary_in_both_languages() -> None:
    fine = [Check("ok", "browsers", "Edge")]
    broken = [*fine, Check("FAIL", "loopback", "x"), Check("FAIL", "loopback", "y")]
    assert summary_line(fine) == "ready: all checks passed"
    assert summary_line(fine, "pl") == "gotowe: wszystkie sprawdzenia zakończone powodzeniem"
    assert summary_line(broken, "pl") == "niegotowe: loopback"
