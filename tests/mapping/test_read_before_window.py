"""The screen before a click on a list's row, read before the list's window was all there (a
server's answer later), shows neither the row nor the window's OK: OK missing from it is no
sign of what the click did (benchmark D08: the row's step expected OK to appear, and it was
there all along when the robot clicked)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from maptelo.mapping.build import _read_before_its_window
from maptelo.trace.schema import ElementInfo

ROW = ElementInfo(
    tag="java:label", role="option", name="31830-D / 600000001 / Firma", dialog="Customer Items"
)
OK = ElementInfo(tag="java:push button", role="button", name="OK", dialog="Customer Items")
FORM_ONLY = '- region "Price Lists":\n  - textbox "Product Value": 31830%'
LIST_SHOWN = FORM_ONLY + '\n- region "Customer Items":\n  - option "31830-D / 600000001 / Firma"'


def act(target: ElementInfo) -> Any:
    return SimpleNamespace(event=SimpleNamespace(target=target))


def test_a_screen_without_the_row_clicked_says_nothing_of_the_next_button() -> None:
    assert _read_before_its_window(act(ROW), OK, FORM_ONLY)


def test_a_screen_showing_the_row_still_tells_the_button_that_came() -> None:
    assert not _read_before_its_window(act(ROW), OK, LIST_SHOWN)


def test_a_button_of_another_window_is_told_as_before() -> None:
    other = ElementInfo(tag="java:push button", role="button", name="OK", dialog="Price Lists")
    assert not _read_before_its_window(act(ROW), other, FORM_ONLY)
