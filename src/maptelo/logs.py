"""The log Studio and Maptelo Lite keep with their data (``~/.maptelo`` or the folder the
installer gives): what they would say in a console, what Maptelo's modules tell (which Java
Access Bridge, through which Python) and every error a request met, with where it happened.
On a company computer without a console it is what a person or IT sends to support. It is
kept small: a few files of a few megabytes, the oldest dropped."""

from __future__ import annotations

import io
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

SIZE = 2_000_000
"""Bytes of one log file before the next one starts."""
KEPT = 3
"""Earlier log files kept beside it (name.log.1 … name.log.3)."""


class _Said(io.TextIOBase):
    """A console that is not there: each line written to it goes to the log."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def write(self, text: str) -> int:
        for line in text.splitlines():
            if line.strip():
                self.logger.info(line.rstrip())
        return len(text)


def keep_log(name: str, *, home: Path | None = None) -> Path:
    """Log to <data folder>/<name>.log (rotated); with no console (pythonw), what would be
    printed goes there too. The log file's path."""
    if home is None:
        from maptelo.browser import HOME

        home = HOME
    home.mkdir(parents=True, exist_ok=True)
    path = home / f"{name}.log"
    logger = logging.getLogger("maptelo")
    if not any(getattr(h, "baseFilename", None) == str(path) for h in logger.handlers):
        handler = RotatingFileHandler(path, maxBytes=SIZE, backupCount=KEPT, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        if logger.level == logging.NOTSET or logger.level > logging.INFO:
            logger.setLevel(logging.INFO)
    if sys.stdout is None or sys.stderr is None:  # no console: the shortcut starts pythonw
        said = _Said(logging.getLogger("maptelo.console"))
        sys.stdout = sys.stderr = said
    return path
