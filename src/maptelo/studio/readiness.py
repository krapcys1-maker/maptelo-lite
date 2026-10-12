"""Getting a computer ready in Studio: browser profiles that keep a sign-in.

What ``maptelo session save --profile`` does, from the page: the person signs in once in a
window Studio opens on a profile (the check of a process's run is the full Maptelo's). The
page names profiles only by name (they live in ~/.maptelo/profiles): it never points Studio at
a folder of its choosing.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from maptelo import formerly
from maptelo.browser import (
    HOME,
    PROFILES,
    kept_cookies,
    profile_context,
    profile_dir,
    remember_sign_in,
)
from maptelo.studio.common import BROWSERS, RunProblemError
from maptelo.studio.jobs import Job
from maptelo.studio.window import out_of_the_way

PROFILE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
SIGN_IN_MINUTES = 15


def profiles_view(root: Path | None = None) -> list[dict[str, Any]]:
    """The profiles on this computer and when each last kept a sign-in."""
    folder = root or formerly.carried(PROFILES, HOME)
    found = []
    if folder.is_dir():
        for profile in sorted(p for p in folder.iterdir() if p.is_dir()):
            kept = kept_cookies(profile)
            found.append(
                {
                    "name": profile.name,
                    "signed_in": (
                        datetime.fromtimestamp(kept.stat().st_mtime).isoformat(timespec="minutes")
                        if kept.is_file()
                        else None
                    ),
                }
            )
    return found


def _text(data: Mapping[str, Any], name: str) -> str | None:
    value = data.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise RunProblemError([f"'{name}' must be text"])
    return value.strip()


@dataclass(frozen=True)
class SignInRequest:
    profile: str
    url: str
    browser: str = "chromium"

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SignInRequest:
        return cls(
            profile=_text(data, "profile") or "",
            url=_text(data, "url") or "",
            browser=_text(data, "browser") or "chromium",
        )

    def problems(self) -> list[str]:
        found = []
        if not PROFILE_NAME.fullmatch(self.profile):
            found.append(
                "the profile name must be small letters, digits, - or _ (up to 64), e.g. praca"
            )
        if not self.url.startswith(("http://", "https://")):
            found.append("the address must start with http:// or https://")
        if self.browser not in BROWSERS:
            found.append(f"the browser must be one of: {', '.join(BROWSERS)}")
        return found


def sign_in_work(request: SignInRequest) -> Callable[[Job], dict[str, Any]]:
    """A window on the profile at the address: the person signs in and closes it."""
    if problems := request.problems():
        raise RunProblemError(problems)

    def work(job: Job) -> dict[str, Any]:
        folder = profile_dir(request.profile)
        deadline = time.monotonic() + SIGN_IN_MINUTES * 60
        with (
            out_of_the_way(),  # the sign-in window in front, Studio back after
            sync_playwright() as playwright,
            profile_context(
                playwright, folder, headless=False, channel=BROWSERS[request.browser]
            ) as context,
        ):
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(request.url)
            job.emit("open", profile=request.profile, url=request.url)
            while not page.is_closed() and not job.stop_requested:
                if time.monotonic() > deadline:
                    break
                remember_sign_in(context, folder)  # the window may close any moment
                with contextlib.suppress(PlaywrightError):
                    page.wait_for_timeout(1000)
        kept = kept_cookies(folder).is_file()
        return {"profile": request.profile, "kept": kept}

    return work
