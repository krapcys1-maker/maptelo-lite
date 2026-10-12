"""Personal and confidential data on screenshots: covered when a process is private.

A private process (``maptelo record --private``; the model then says ``private: true``)
keeps the layout of a screen on its screenshots, so documents still show where to click,
but covers where personal data usually is: what was typed into fields, what tables hold,
record titles, breadcrumbs and messages. Free text elsewhere on a screen stays visible;
screens like that are better recorded with ``--no-screenshots``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import Page

MASK_SELECTOR = ", ".join(
    [
        "input:not([type=hidden]):not([type=checkbox]):not([type=radio])"
        ":not([type=submit]):not([type=button]):not([type=reset])",
        "textarea",
        "select",
        "[contenteditable]:not([contenteditable=false])",
        "td",
        "[role=cell]",
        "[role=gridcell]",
        "[role=option]",
        "h1, h2, h3, h4, h5, h6, [role=heading]",  # a record's title is often a name
        "[class*=breadcrumb], [class*=Breadcrumb], nav[aria-label*=readcrumb]",
        "[role=alert], [role=status], output",  # messages name the record they are about
    ]
)
MASK_COLOR = "#9CA3AF"
"""A quiet grey: the covered places still read as fields and cells."""


def screenshot(page: Page, path: Path, *, private: bool, **options: Any) -> None:
    """A screenshot; when private, what is typed and what tables hold is covered."""
    if private:
        options |= {"mask": [page.locator(MASK_SELECTOR)], "mask_color": MASK_COLOR}
    page.screenshot(path=path, **options)
