"""Maptelo's own connections: the independent read, AI repairs, the doctor's knock.

On a company network, HTTPS often goes through a proxy that inspects TLS with the company's
certificate. Python checks a certificate chain itself, with its copy of the trusted roots;
Windows (and Edge) check it with the system's rules, which also fetch missing intermediate
certificates and apply the company's trust settings. With truststore, Maptelo asks the
system, as the browser does, so what works in Edge works here (docs/08-srodowiska.md).
The proxy comes from the environment (HTTPS_PROXY) or from Windows' settings, as urllib reads
them.
"""

from __future__ import annotations

import ssl
import urllib.request
from functools import cache
from http.client import HTTPResponse

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


def open_url(request: urllib.request.Request | str, timeout: float) -> HTTPResponse:
    """urllib's urlopen with the system's trust; the proxy as Windows or the environment says."""
    response: HTTPResponse = urllib.request.urlopen(
        request, timeout=timeout, context=https_context()
    )
    return response
