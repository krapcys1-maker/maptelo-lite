"""What Maptelo wrote when it was called Stepproof (until October 2026), read here and only here.

Recordings made before keep their header (``stepproof-trace/0.1``, ``stepproof-recorder``) and
are read as today's. The folder in the person's home (``~/.stepproof``: browser profiles that
stay signed in) is moved to ``~/.maptelo`` the first time it is needed. IT's policy put where
the old name said (``%ProgramData%\\Stepproof``, ``STEPPROOF_POLICY``) still applies: rules
that are there must not stop applying because the program changed its name.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

TRACE_NAMES = {
    "stepproof-trace/0.1": "maptelo-trace/0.1",
    "stepproof-recorder": "maptelo-recorder",
}
"""A recording's header from before: what each old value is called now."""

HOME = Path.home() / ".stepproof"
COOKIES = "stepproof-cookies.json"
POLICY_ENV = "STEPPROOF_POLICY"
POLICY_FOLDER = "Stepproof"
"""The folder under %ProgramData% where IT put the policy."""


def carried(path: Path, home: Path, old_home: Path | None = None) -> Path:
    """``path`` in Maptelo's ``home``, with what the old home had there moved over.

    Moved when first needed; when it cannot be moved (a browser still has a profile in it
    open, the disk says no), it is used where it is. A path outside ``home`` comes back as it
    is (a profile given by its path, a test's folder)."""
    try:
        inside = path.relative_to(home)
    except ValueError:
        return path
    old = (HOME if old_home is None else old_home) / inside
    if path.exists() or not old.exists():
        return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        old.rename(path)
    except OSError:
        return old
    return path


def carried_cookies(folder: Path, name: str) -> Path:
    """A profile's cookies file, renamed from the old name when that is what the profile has.

    When it cannot be renamed, the old file is read where it is."""
    path = folder / name
    old = folder / COOKIES
    if path.exists() or not old.is_file():
        return path
    with contextlib.suppress(OSError):
        old.rename(path)
    return path if path.exists() else old
