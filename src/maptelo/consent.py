"""A site's own window asking for consents (cookies, privacy): answering it is no work of the
process, though it sends the choice (benchmark M5, M6: „Pliki cookie i zgody”). The map does not
count it as a save; the robot does not take its request for a write of the record. A window no
recording showed, in the way of a step, is answered with the choice that consents to nothing
beyond what the site needs (benchmark M7 r7: the map of a recording made after the consent was
given stopped at every record under the banner)."""

from __future__ import annotations

import re
from collections.abc import Iterable

CONSENT = re.compile(r"cookie|ciasteczk|\bzgod(?!n)|\bzgód|consent|privacy|prywatno", re.IGNORECASE)

NECESSARY_ONLY = re.compile(
    r"tylko (?:niezbędne|wymagane|konieczne)|odrzuć|odmawiam|nie zgadzam|"
    r"only (?:the )?(?:necessary|essential|required)|"
    r"(?:necessary|essential|required)(?: cookies)? only|"
    r"reject|decline|refuse",
    re.IGNORECASE,
)
"""The words of a consent window's button that consents to nothing beyond what is needed."""


COOKIES = re.compile(r"cookie|ciasteczk|privacy|prywatno", re.IGNORECASE)
"""A site's own banner about cookies and privacy (not a consent of the process: „Zgoda RODO” in
a form of the company's HR system is the person's decision, never answered by the robot)."""


def consent_window(name: str | None) -> bool:
    """The window's title asks for consents."""
    return bool(name) and CONSENT.search(name or "") is not None


def cookie_window(name: str | None) -> bool:
    """The window's title is a site's cookie or privacy banner."""
    return bool(name) and COOKIES.search(name or "") is not None


def necessary_only(buttons: Iterable[str]) -> str | None:
    """Of a consent window's buttons, the first that consents to nothing beyond what the site
    needs („Tylko niezbędne”, „Odrzuć wszystkie”); None when it has no such button."""
    return next((b for b in buttons if NECESSARY_ONLY.search(b)), None)
