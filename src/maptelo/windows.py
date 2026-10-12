"""Windows over the main window, as old programs (billing, pricing) open them: a chooser that
fills a field and closes, an approval, and the browser's own questions (``confirm``,
``prompt``) asked before a save.

A window is told by how deep it is: 0 the first window, 1 a window opened from it, 2 a
window opened from that one. Not by the order windows opened in: a chooser opened again for
each line of an order is a new window each time, and still the same one for the process.
The recorder, the runtime and the exported script share this code.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any, Protocol


class _Window(Protocol):
    def is_closed(self) -> bool: ...


# The exported script carries this module from here on (export/playwright_py.py).


def latest_open(windows: Sequence[_Window]) -> int:
    """The window to work in when the one worked in closed: the last one opened that is
    still open (the first window, when no other is)."""
    for index in range(len(windows) - 1, 0, -1):
        if not windows[index].is_closed():
            return index
    return 0


def window_at(windows: Sequence[_Window], depths: Sequence[int], depth: int) -> int | None:
    """The open window as deep as ``depth`` (the last opened, when several are), if any."""
    for index in range(len(windows) - 1, -1, -1):
        if depths[index] == depth and not windows[index].is_closed():
            return index
    return None


NEGATIONS = frozenset({"nie", "not", "no", "don't", "dont", "nicht", "kein", "keine"})
"""Words that turn a question around: „Czy nie zapisywać?” is not „Czy zapisywać?”."""


def question_words(text: str) -> frozenset[str]:
    """The words of a question, numbers as one: „Usuń 3 pozycje” is „Usuń 4 pozycje”."""
    return frozenset(re.sub(r"\d+", "#", word) for word in re.findall(r"[\w']+", text.casefold()))


def same_question(recorded: str, shown: str) -> bool:
    """Whether a dialog asks what the recorded one asked: every word of the recorded question
    is in it (words may be added: „Zapisać zmiany?” is „Czy zapisać zmiany?”), and neither
    turns it around where the other does not."""
    was, now = question_words(recorded), question_words(shown)
    return (was & NEGATIONS) == (now & NEGATIONS) and was <= now


def recorded_answer(
    dialogs: Sequence[dict[str, Any]],
    answered: set[int],
    kind: str,
    message: str,
    fill: Callable[[str], str],
) -> int | None:
    """Which of a step's recorded dialogs this one is (an index of ``dialogs`` not
    ``answered`` yet), if any: of the same kind and asking the same, the record's own values
    put into the recorded words (``fill``)."""
    for index, dialog in enumerate(dialogs):
        if index in answered or dialog.get("kind") != kind:
            continue
        recorded = dialog.get("message")
        if recorded is None or same_question(fill(recorded), message):
            return index
    return None
