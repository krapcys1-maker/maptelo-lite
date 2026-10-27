"""HTTPS from Python with the operating system's trust, as in the browser (truststore).

Lite itself connects nowhere: the browser it records in does, with Windows' settings.
SYSTEM_TRUST is what the Readiness tab says about certificates.
"""

from __future__ import annotations

import ssl
import urllib.request
from functools import cache
from http.client import HTTPResponse
from typing import Any
from urllib.parse import urlsplit

try:
    import truststore
except ImportError:  # pragma: no cover - truststore is a dependency; kept optional for safety
    truststore = None  # type: ignore[assignment]

SYSTEM_TRUST = truststore is not None
"""Whether HTTPS certificates are checked by the operating system (as in the browser)."""


@cache
def https_context() -> ssl.SSLContext:
    """One context for every HTTPS connection Maptelo makes."""
    if truststore is not None:
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return ssl.create_default_context()


CREDENTIALS = frozenset(
    {"authorization", "proxy-authorization", "api-key", "x-api-key", "cookie", "x-goog-api-key"}
)
"""Headers that carry a key or a sign-in: they go to the address asked, never further."""


class _KeysStayHome(urllib.request.HTTPRedirectHandler):
    """A redirect to another host (or from HTTPS to HTTP) is followed without the key: the
    service asked holds the key, the one it sends Maptelo to does not."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        before, after = urlsplit(req.full_url), urlsplit(newurl)
        same = (before.scheme, before.hostname, before.port) == (
            after.scheme,
            after.hostname,
            after.port,
        )
        if not same:
            for name in list(new.headers):
                if name.lower() in CREDENTIALS:
                    del new.headers[name]
            for name in list(new.unredirected_hdrs):
                if name.lower() in CREDENTIALS:
                    del new.unredirected_hdrs[name]
        return new


@cache
def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=https_context()), _KeysStayHome()
    )


def open_url(request: urllib.request.Request | str, timeout: float) -> HTTPResponse:
    """urllib's urlopen with the system's trust; the proxy as Windows or the environment says;
    a key is not sent on to another host a redirect names."""
    response: HTTPResponse = _opener().open(request, timeout=timeout)
    return response
