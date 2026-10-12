"""Which requests send data to an application, so may save something, and which only read.

What saves is a POST, PUT, PATCH or DELETE; what only reads is a GET. Some applications read
with POST too: Odoo asks for every list and form through JSON-RPC, naming the method it calls
(``web_search_read`` reads, ``web_save`` or ``action_confirm`` writes), and pages keep a
session alive or listen for news with POSTs that save nothing. Those are told apart by where
they go. Anything not known to only read counts as sending data: in doubt, a save.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from maptelo.model.urls import path_template

# The exported script carries this module from here on (export/playwright_py.py).
READING_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_ODOO_CALL = re.compile(r"/web/dataset/call_(?:kw|button)/[\w.]+/(?P<method>\w+)")
ODOO_READS = frozenset(
    {
        "check_access_rights",
        "check_access_rule",
        "default_get",
        "fields_get",
        "get_formview_action",
        "get_formview_id",
        "get_views",
        "has_group",
        "load_views",
        "name_get",
        "name_search",
        "onchange",
        "read",
        "read_group",
        "read_progress_bar",
        "search",
        "search_count",
        "search_read",
        "web_name_search",
        "web_read",
        "web_read_group",
        "web_search_read",
    }
)
"""Odoo methods that only read; any other method may write (``web_save``, ``action_*``)."""
_ONLY_READS = frozenset(
    {
        "/session/keepalive",
        "/bus/im_status",
        "/web/action/load",
        "/web/session/get_session_info",
        "/web/webclient/load_menus",
        "/web/webclient/translations",
        "/mail/data",
        "/mail/thread/data",
        "/mail/thread/messages",
        "/mail/thread/recipients",
        "/mail/inbox/messages",
        "/mail/starred/messages",
        "/mail/history/messages",
    }
)
"""Paths that answer a POST without saving: keeping a session, news, statistics, Odoo's
menus, actions, session information and the messages shown beside a record."""


def sends_data(method: str, url: str) -> bool:
    """Whether this request may save something in the application."""
    if method.upper() in READING_METHODS:
        return False
    path = urlsplit(url).path
    call = _ODOO_CALL.fullmatch(path)
    if method.upper() == "POST" and call is not None:
        return call.group("method") not in ODOO_READS
    return method.upper() != "POST" or path not in _ONLY_READS


# END_CARRIED


def describe(method: str, url: str, *, private: bool = False) -> str:
    """``POST /orders/12/invoice``: the method and the path, never what was sent; in a private
    recording the path's numbers and codes are left out too (``/orders/*/invoice``)."""
    path = urlsplit(url).path or "/"
    return f"{method.upper()} {path_template(path) if private else path}"
