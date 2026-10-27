"""Versions of the files Maptelo writes (a recording, a process model) and how files of an
earlier version are read: each file says the version of its format, a file of an earlier
one is brought up to this one step by step (``MIGRATIONS``) before it is checked, and a file
of a later one is refused with a sentence that says what to do (a newer Maptelo made it),
not with the checker's „Extra inputs are not permitted”.

A format's version goes up when a file this Maptelo writes would not be read by the one
before it: a new field, a renamed one, a value with a new meaning.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Migration = Callable[[dict[str, Any]], dict[str, Any]]

MODEL_VERSIONS = ("0.1",)
"""The process model's formats this Maptelo reads, oldest first; the last is the one it
writes."""
TRACE_VERSIONS = ("maptelo-trace/0.1",)
"""The recording's formats, the same way."""

MIGRATIONS: dict[str, Migration] = {}
"""A format's version -> how a file of it becomes a file of the next one."""


class NewerFormatError(ValueError):
    """A file of a format later than this Maptelo knows."""


def _parts(version: str) -> tuple[int, ...]:
    tail = version.rpartition("/")[2]
    try:
        return tuple(int(p) for p in tail.split("."))
    except ValueError:
        return (0,)


def upgraded(data: dict[str, Any], key: str, known: tuple[str, ...], what: str) -> dict[str, Any]:
    """``data`` in the format this Maptelo writes; NewerFormatError for a later one."""
    given = data.get(key)
    if not isinstance(given, str):
        return data  # the checker says what is wrong with it
    if given not in known and _parts(given) > _parts(known[-1]):
        raise NewerFormatError(
            f"{what} was made by a newer Maptelo (its format {given}; this one reads up to "
            f"{known[-1]}): update Maptelo to open it"
        )
    while data.get(key) in MIGRATIONS and data.get(key) != known[-1]:
        data = MIGRATIONS[str(data[key])](dict(data))
    return data
