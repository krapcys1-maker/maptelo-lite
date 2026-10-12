"""What every part of Studio shares: the browsers a person can choose, and the problems a
request has before any work starts (said back on the page, each in its own sentence)."""

from __future__ import annotations

BROWSERS = {"chromium": None, "msedge": "msedge", "chrome": "chrome"}
"""The browsers offered, by name: Playwright's own Chromium, or the company's Edge or Chrome."""


class RunProblemError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems
