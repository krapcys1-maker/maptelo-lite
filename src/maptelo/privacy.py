"""Personal and confidential data on screenshots: covered when a process is private.

A private process (``maptelo record --private``; the model then says ``private: true``)
keeps the layout of a screen on its screenshots, so documents still show where to click,
but covers where personal data usually is: what was typed into fields, what tables hold,
record titles, breadcrumbs and messages. Free text elsewhere on a screen stays visible;
screens like that are better recorded with ``--no-screenshots``.

The documents made of a private process for people to read and share (SOP, report,
diagrams, BPMN, AI brief) show no value a person typed or chose in its recordings
(``redact``); the model itself keeps what a run needs, and stays with the company.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from playwright.sync_api import Page

if TYPE_CHECKING:
    from maptelo.trace.schema import Trace

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
    """A screenshot; when private, what is typed and what tables hold is covered, in every
    frame of the page (a form inside an iframe or a frameset is the page's too)."""
    if private:
        masks = [frame.locator(MASK_SELECTOR) for frame in page.frames]
        options |= {"mask": masks, "mask_color": MASK_COLOR}
    page.screenshot(path=path, **options)


HIDDEN = {"pl": "[wartość]", "en": "[value]"}
"""What stands in a shared document of a private process where a recorded value was."""


def recorded_values(traces: Iterable[Trace]) -> list[str]:
    """The values people typed, chose or sent as files in these recordings (never a secret's,
    which is not kept), longest first: what a private process's shared documents must not
    show. A value of one or two signs, or a small number, stands anywhere by chance."""
    found: set[str] = set()
    for trace in traces:
        for event in trace.events:
            if event.secret:
                continue
            for value in [event.value, *(event.files or [])]:
                text = " ".join(str(value or "").split())
                if len(text) >= 3 and not (text.isdigit() and len(text) <= 3):
                    found.add(text)
    return sorted(found, key=len, reverse=True)


def redact(text: str, values: Sequence[str], lang: str = "pl") -> str:
    """The text with every recorded value covered, as written and as HTML or XML writes it."""
    hidden = HIDDEN.get(lang, HIDDEN["en"])
    for value in values:
        for form in {value, html.escape(value), html.escape(value, quote=False)}:
            text = text.replace(form, hidden)
    return text
