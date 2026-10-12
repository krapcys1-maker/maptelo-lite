"""How long the evidence of runs is kept: screenshots, and files a run downloaded (a parcel's
label). They may show personal data (docs/06-prywatnosc.md), so a company keeps them only as
long as it needs: IT's policy (``evidence.keep_days``) or ``maptelo cleanup --keep-days``.
Only those go; what each run found (results, reports, the sheet with results) stays.

    runs/<process>/<run>/evidence/*.png          runs from the command line and Studio
    runs/<process>/<run>/evidence/files/...      files the run downloaded
    shadow/<process>/<check>/evidence/*.png      shadow checks
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PICTURES = (".png", ".jpg", ".jpeg")
FOLDERS = ("runs", "shadow")
LOG = "retention.log"
DAY_S = 86_400


@dataclass(frozen=True)
class Swept:
    removed: list[Path] = field(default_factory=list)
    size: int = 0
    """Bytes freed (or that would be, in a dry run)."""


def old_evidence(workspace: Path, keep_days: int, now: float | None = None) -> list[Path]:
    """Screenshots and downloaded files older than ``keep_days`` (by the file's time), in the
    evidence folders."""
    limit = (time.time() if now is None else now) - keep_days * DAY_S
    found = []
    for name in FOLDERS:
        root = workspace / name
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            kept = "files" in path.parts or path.suffix.lower() in PICTURES
            if not kept or "evidence" not in path.parts:
                continue
            try:
                if path.is_file() and path.stat().st_mtime < limit:
                    found.append(path)
            except OSError:
                continue
    return sorted(found)


def days_to_keep(asked: int | None, policy_days: int | None) -> int | None:
    """How long to keep: IT's policy is the most; a person may keep less, never more."""
    if asked is not None and policy_days is not None:
        return min(asked, policy_days)
    return asked if asked is not None else policy_days


def sweep(
    workspace: Path, keep_days: int, *, dry_run: bool = False, now: float | None = None
) -> Swept:
    """Remove the evidence older than ``keep_days``; a line in retention.log says so."""
    removed, size = [], 0
    for path in old_evidence(workspace, keep_days, now):
        try:
            bytes_ = path.stat().st_size
            if not dry_run:
                path.unlink()
        except OSError:
            continue  # in use or gone: next time
        removed.append(path)
        size += bytes_
    if removed and not dry_run:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        line = f"{stamp} removed {len(removed)} evidence files older than {keep_days} days"
        with (workspace / LOG).open("a", encoding="utf-8") as log:
            log.write(f"{line} ({size} bytes)\n")
    return Swept(removed, size)
