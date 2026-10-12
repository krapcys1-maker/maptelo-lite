"""What every part of Studio shares: the browsers a person can choose, the problems a request
has before any work starts (said back on the page, each in its own sentence), and the page's
language as the person chose it."""

from __future__ import annotations

import json
from pathlib import Path

from maptelo.mapping.naming import Lang

BROWSERS = {"chromium": None, "msedge": "msedge", "chrome": "chrome"}
"""The browsers offered, by name: Playwright's own Chromium, or the company's Edge or Chrome."""


class RunProblemError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _settings() -> Path:
    from maptelo import browser  # its HOME is where this person's things are (MAPTELO_HOME)

    return browser.HOME / "studio.json"


def page_language() -> Lang | None:
    """The page's language as the person last chose it (Maptelo Lite), if they did. Kept with
    the profiles: the window's address changes at every start, and with it the browser's own
    storage."""
    try:
        said = json.loads(_settings().read_text(encoding="utf-8")).get("lang")
    except (OSError, ValueError, AttributeError):
        return None
    if said == "pl":
        return "pl"
    return "en" if said == "en" else None


def keep_page_language(lang: Lang) -> None:
    path = _settings()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"lang": lang}), encoding="utf-8")
