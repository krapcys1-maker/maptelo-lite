"""Files people's work is kept in (notes, the process card, questions, models, repairs), written
whole or not at all: the text goes to a file of its own beside the old one, which it then
replaces in one move. A computer that stops in the middle (a power cut, a killed window)
leaves the old file as it was, never half of the new one."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path


def write_atomic(
    path: Path, text: str, encoding: str = "utf-8", newline: str | None = None
) -> None:
    """``path.write_text(text, ...)`` that leaves either the old file or the new one."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding=encoding, newline=newline) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
