"""The browser a run uses: the one people use, in their time zone and language.

With a profile (``--profile praca``) the browser keeps its own folder between runs, like a
person's browser: sign in once there (also through a company's single sign-on) and every
recording and run after that is signed in, with no session file in the project. A profile
given by name lives in ``~/.maptelo/profiles`` (or under ``MAPTELO_HOME``), never in a project
folder, because it holds the sign-in. Two things a plain browser profile does not do, a
Maptelo profile does: it keeps session cookies (many applications sign in with cookies a
browser forgets when it closes) and it is used by one browser at a time (two would spoil each
other's sign-in).
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, Playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from maptelo import formerly
from maptelo.model.schema import ProcessModel
from maptelo.policy import PolicyError
from maptelo.policy import current as current_policy

HOME = Path(os.environ.get("MAPTELO_HOME") or Path.home() / ".maptelo")
"""What Maptelo keeps for this person: sign-in profiles, its window's browser data. In their
home (the folder from before the rename is moved here, formerly.py), or where MAPTELO_HOME
says: Maptelo Lite's installer keeps it in Lite's own folder, nothing in the user's profile."""
PROFILES = HOME / "profiles"
COOKIES = "maptelo-cookies.json"
"""The profile's cookies, session cookies too, kept in the profile folder."""
SANDBOX = sys.platform == "win32"
"""The browser's own sandbox, as Edge and Chrome run on every Windows computer, also for a
person without administrator rights. Playwright turns it off unless asked, and a window then
warns "--no-sandbox … security risks" (the clean-Windows test of 11.10). Off elsewhere: a Linux
container often cannot give the sandbox what it needs."""


class ProfileError(Exception):
    """The profile cannot be opened (a browser has it open, or it cannot start)."""


class AddressError(RuntimeError):
    """The address cannot be opened at all: no such server, no network, a refused connection."""


def open_address(page: Page, url: str) -> None:
    """Open where a person starts working. The page's document is enough: a page that keeps
    loading (a news portal's adverts and trackers, which never let "load" come) is there to
    work in already, and one slower still is worked in as it comes. Only an address that
    cannot be reached at all stops the work, in a sentence a person reads."""
    try:
        page.goto(url, wait_until="domcontentloaded")
    except PlaywrightTimeoutError:
        return
    except PlaywrightError as exc:
        first = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        reason = first.removeprefix("Page.goto: ").split(" at ")[0]
        raise AddressError(f"cannot open {url}: {reason}") from exc


@dataclass(frozen=True)
class BrowserSettings:
    storage_state: Path | None = None
    """A signed-in session from ``maptelo session save`` (instead of a profile)."""
    headed: bool = False
    channel: str | None = None
    """An installed browser instead of Playwright's Chromium: chrome or msedge."""
    timezone: str | None = None
    """Default: the model's, where people do the process."""
    locale: str | None = None
    timeout_ms: int = 10_000
    profile: str | None = None
    """A browser profile that stays signed in: a name (in ~/.maptelo/profiles) or a path."""
    company_certificates: bool = False
    """Accept the company's own certificates, as its computers do (IT's policy decides first)."""


def profile_dir(profile: str) -> Path:
    """Where a profile lives: a name goes to ~/.maptelo/profiles, a path is kept."""
    if any(sign in profile for sign in ("/", "\\", ":")) or profile.startswith((".", "~")):
        return Path(profile).expanduser()
    return formerly.carried(PROFILES, HOME) / profile


def kept_cookies(folder: Path) -> Path:
    """The profile's cookies file (one kept under the old name is renamed, formerly.py)."""
    return formerly.carried_cookies(folder, COOKIES)


@contextlib.contextmanager
def _one_at_a_time(folder: Path) -> Iterator[None]:
    """A lock the system lets go of when the process ends, even when it crashes."""
    handle = (folder / "maptelo.lock").open("a+b")
    try:
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ProfileError(
                f"the profile {folder} is in use by another Maptelo browser: "
                "wait for it to finish, or use another profile"
            ) from exc
        yield
    finally:
        handle.close()


@contextlib.contextmanager
def profile_context(
    playwright: Playwright,
    folder: Path,
    *,
    headless: bool = True,
    channel: str | None = None,
    **options: Any,
) -> Iterator[BrowserContext]:
    """A browser on a profile folder: one at a time, its cookies back from the last time,
    and kept again when it closes."""
    folder.mkdir(parents=True, exist_ok=True)
    with _one_at_a_time(folder):
        try:
            context = playwright.chromium.launch_persistent_context(
                folder, headless=headless, channel=channel, chromium_sandbox=SANDBOX, **options
            )
        except PlaywrightError as exc:
            raise ProfileError(
                f"the profile {folder} cannot be opened: {str(exc).splitlines()[0]}"
            ) from exc
        cookies = kept_cookies(folder)
        if cookies.is_file():
            with contextlib.suppress(PlaywrightError, OSError, ValueError, KeyError):
                context.add_cookies(json.loads(cookies.read_text(encoding="utf-8"))["cookies"])
        try:
            yield context
        finally:
            remember_sign_in(context, folder)
            with contextlib.suppress(PlaywrightError):
                context.close()


def remember_sign_in(context: BrowserContext, folder: Path) -> None:
    """Keep the profile's cookies (also those a browser forgets when it closes)."""
    with contextlib.suppress(PlaywrightError, OSError):
        context.storage_state(path=str(folder / COOKIES))


def zone_and_language(
    model: ProcessModel | None, settings: BrowserSettings
) -> tuple[str | None, str | None]:
    if model is None:
        return settings.timezone, settings.locale
    return (
        settings.timezone or model.application.timezone,
        settings.locale or model.application.locale,
    )


def trusts_company_certificates(settings: BrowserSettings) -> bool:
    """IT's policy decides when it says; else the run's own setting."""
    try:
        rule = current_policy().rules.browser.company_certificates
    except PolicyError:
        return False
    return settings.company_certificates if rule is None else rule


@contextlib.contextmanager
def browser_context(
    playwright: Playwright, model: ProcessModel | None, settings: BrowserSettings
) -> Iterator[BrowserContext]:
    """A browser like the people who do the process use; closed when the block ends.
    The browser IT's policy names is the one used, whichever was asked for."""
    with contextlib.suppress(PolicyError):  # an unreadable policy stops the run itself
        rules = current_policy().rules.browser
        if rules.channel is not None:
            settings = replace(
                settings, channel=None if rules.channel == "chromium" else rules.channel
            )
    zone, language = zone_and_language(model, settings)
    options: dict[str, Any] = {
        "viewport": {"width": 1280, "height": 860},
        "timezone_id": zone,
        "locale": language,
        "service_workers": "block",
    }
    if trusts_company_certificates(settings):
        options["ignore_https_errors"] = True  # the robot opens only the allowed addresses
    if settings.profile is not None:
        folder = profile_dir(settings.profile)
        with profile_context(
            playwright, folder, headless=not settings.headed, channel=settings.channel, **options
        ) as context:
            context.set_default_timeout(settings.timeout_ms)
            yield context
        return
    browser = playwright.chromium.launch(
        headless=not settings.headed, channel=settings.channel, chromium_sandbox=SANDBOX
    )
    try:
        context = browser.new_context(
            storage_state=str(settings.storage_state) if settings.storage_state else None,
            **options,
        )
        context.set_default_timeout(settings.timeout_ms)
        yield context
    finally:
        with contextlib.suppress(PlaywrightError):
            browser.close()
