"""One check of a computer or a process, as the doctor, the environment probe and Studio
show it: a verdict, what was checked, what was found and what to do about it.

The command line speaks English and Studio Polish, so every sentence is written in both
(``say``); what a check is about (``what``) stays an English key the page translates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Verdict = Literal["ok", "FAIL", "info"]
Lang = Literal["en", "pl"]


def say(lang: Lang, en: str, pl: str) -> str:
    return pl if lang == "pl" else en


@dataclass(frozen=True)
class Check:
    verdict: Verdict
    what: str
    detail: str
    hint: str = ""

    def __str__(self) -> str:
        line = f"  {self.verdict:<5} {self.what}: {self.detail}"
        return line + (f"\n        -> {self.hint}" if self.hint else "")


def summary_line(checks: list[Check], lang: Lang = "en") -> str:
    failed = [c.what for c in checks if c.verdict == "FAIL"]
    if not failed:
        return say(
            lang, "ready: all checks passed", "gotowe: wszystkie sprawdzenia zakończone powodzeniem"
        )
    return say(lang, "not ready: ", "niegotowe: ") + ", ".join(dict.fromkeys(failed))
