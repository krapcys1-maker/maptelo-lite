"""Which screen an address shows.

Classic web applications show a screen per path (``/pricing/product/C001/48212-B``).
Single-page applications often keep one path and say the screen after ``#``
(``/web#action=175&model=product.pricelist&view_type=list&menu_id=181``). A screen is the
path plus that fragment, without what only identifies a record or a menu entry: numbers
and code-like segments become ``*`` in a path and are left out of a fragment's parameters.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Mapping
from urllib.parse import parse_qsl, unquote_plus, urlsplit, urlunsplit

_NUMBER = re.compile(r"^\d+(?:,\d+)*$")


def origin(url: str | None) -> str:
    """``https://erp.example.com:8443`` of an address: which application it belongs to."""
    parts = urlsplit(url or "")
    return f"{parts.scheme}://{parts.netloc}"


def names_record(segment: str) -> bool:
    """A part of a path that identifies a record rather than a screen: a number or a code."""
    return any(ch.isdigit() for ch in segment) or (segment.isupper() and len(segment) <= 12)


def path_template(path: str) -> str:
    """``/pricing/product/C001/48212-B`` -> ``/pricing/product/*/*``."""
    parts = ["*" if names_record(seg) else seg for seg in path.split("/")]
    return "/".join(parts) or "/"


def fragment_template(fragment: str) -> str:
    """``action=175&model=product.pricelist&view_type=list`` -> ``model=product.pricelist&
    view_type=list`` (sorted); a hash-router path (``/orders/12``) is treated like a path."""
    if not fragment:
        return ""
    if "=" not in fragment:
        return path_template(fragment)
    kept = sorted(
        (key, value)
        for key, value in parse_qsl(fragment, keep_blank_values=True)
        if value and not _NUMBER.match(value)
    )
    return "&".join(f"{key}={value}" for key, value in kept)


def screen_template(url: str) -> str:
    parts = urlsplit(url)
    fragment = fragment_template(parts.fragment)
    return path_template(parts.path) + (f"#{fragment}" if fragment else "")


def url_matches(url: str, pattern: str) -> bool:
    """The path matches the pattern's path (a glob); when the pattern has a ``#`` part,
    each of its ``key=glob`` is in the address too (in any order)."""
    path_pattern, has_fragment, fragment_pattern = pattern.partition("#")
    parts = urlsplit(url)
    if not fnmatch.fnmatchcase(parts.path, path_pattern):
        return False
    if not has_fragment or not fragment_pattern:
        return True
    if "=" not in fragment_pattern:
        return fnmatch.fnmatchcase(parts.fragment, fragment_pattern)
    live = dict(parse_qsl(parts.fragment, keep_blank_values=True))
    return all(
        key in live and fnmatch.fnmatchcase(live[key], value)
        for key, value in parse_qsl(fragment_pattern, keep_blank_values=True)
    )


def fill_from(url: str, names: Mapping[str, str]) -> tuple[str, list[str]]:
    """The address with each part that names a record put as the value holding it
    (``/orders/48`` with 48 typed as the input ``order`` -> ``/orders/{inputs.order}``), and
    the parts that name a record and that nothing holds.

    The parts are what a screen's address leaves out: numbers and codes in the path, numbers
    in the query and in the ``#`` part. ``names``: a value -> its reference (``inputs.order``)."""
    unexplained: list[str] = []

    def put(raw: str) -> str:
        reference = names.get(unquote_plus(raw))
        if reference is not None:
            return "{" + reference + "}"
        unexplained.append(unquote_plus(raw))
        return raw

    def pairs(text: str) -> str:
        parts = []
        for pair in text.split("&"):
            key, sep, value = pair.partition("=")
            parts.append(key + sep + (put(value) if sep and _has_digit(value) else value))
        return "&".join(parts)

    parts = urlsplit(url)
    path = "/".join(put(seg) if seg and names_record(seg) else seg for seg in parts.path.split("/"))
    query = pairs(parts.query) if parts.query else ""
    if "=" in parts.fragment:
        fragment = pairs(parts.fragment)
    else:
        fragment = "/".join(
            put(seg) if seg and names_record(seg) else seg for seg in parts.fragment.split("/")
        )
    return urlunsplit((parts.scheme, parts.netloc, path, query, fragment)), unexplained


def _has_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text)
