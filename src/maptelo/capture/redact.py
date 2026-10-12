"""Keeping secrets out of recordings.

Playwright's accessibility snapshot includes the value of every textbox, password fields
included. Before a snapshot is stored, current password values are replaced. The values
are read from the page only for this purpose and never written anywhere.
"""

from __future__ import annotations

from collections.abc import Iterable

REDACTED = "[redacted]"
_MIN_GLOBAL = 4  # shorter secrets are only removed from textbox lines, not everywhere


def redact_secrets(text: str, secrets: Iterable[str]) -> str:
    values = {s for s in secrets if s}
    if not values:
        return text
    lines = []
    for line in text.splitlines():
        head, separator, tail = line.rpartition(": ")
        if separator and "textbox" in head and tail.strip().strip('"') in values:
            line = f"{head}: {REDACTED}"
        lines.append(line)
    redacted = "\n".join(lines)
    for secret in sorted((v for v in values if len(v) >= _MIN_GLOBAL), key=len, reverse=True):
        redacted = redacted.replace(secret, REDACTED)
    return redacted
