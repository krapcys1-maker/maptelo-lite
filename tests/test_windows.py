"""Windows over the main window and the browser's own dialogs (maptelo.windows): which
window a step is done in, which recorded answer a dialog gets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maptelo.windows import latest_open, recorded_answer, same_question, window_at


@dataclass
class Window:
    closed: bool = False

    def is_closed(self) -> bool:
        return self.closed


def test_a_closed_window_gives_way_to_the_last_one_still_open() -> None:
    main, chooser, nested = Window(), Window(), Window(closed=True)
    assert latest_open([main, chooser, nested]) == 1
    assert latest_open([main, Window(closed=True)]) == 0
    assert latest_open([main]) == 0


def test_a_window_is_told_by_how_deep_it_is_not_by_when_it_opened() -> None:
    """A chooser opened again for each line of an order is a new window each time, and
    still the same window of the process: the last one opened that deep."""
    windows = [Window(), Window(closed=True), Window(closed=True), Window()]
    depths = [0, 1, 1, 1]
    assert window_at(windows, depths, 1) == 3
    assert window_at(windows, depths, 0) == 0
    assert window_at(windows, depths, 2) is None
    windows[3].closed = True
    assert window_at(windows, depths, 1) is None


def test_the_same_question_in_other_words_or_numbers() -> None:
    assert same_question("Zapisać zmiany?", "Zapisać zmiany?")
    assert same_question("Zapisać zmiany?", "Czy zapisać zmiany?")  # words added
    assert same_question("Usunąć 3 pozycje?", "Usunąć 4 pozycje?")  # numbers are numbers
    assert same_question("ZAPISAĆ   zmiany?", "zapisać zmiany")
    assert not same_question("Zapisać zmiany?", "Usunąć najem?")
    assert not same_question("Czy chcesz zapisać zmiany?", "Czy chcesz porzucić zmiany?")
    assert not same_question("Czy zapisać zmiany?", "Czy nie zapisywać zmian?")
    assert not same_question("Zapisać zmiany?", "Nie zapisać zmiany?")  # turned around


def test_a_dialog_gets_the_answer_recorded_for_it() -> None:
    recorded: list[dict[str, Any]] = [
        {"kind": "prompt", "message": "Podaj powód zmiany", "value": "$inputs.powod"},
        {"kind": "confirm", "message": "Zapisać zmiany: Najem {inputs.numer}?"},
    ]

    def fill(text: str) -> str:
        return text.replace("{inputs.numer}", "NJ/2026/0002")

    answered: set[int] = set()
    asked = "Zapisać zmiany: Najem NJ/2026/0002?"
    assert recorded_answer(recorded, answered, "confirm", asked, fill) == 1  # in any order
    answered.add(1)
    assert recorded_answer(recorded, answered, "confirm", asked, fill) is None  # once
    assert recorded_answer(recorded, answered, "prompt", "Podaj powód zmiany:", fill) == 0
    assert recorded_answer(recorded, set(), "alert", "Podaj powód zmiany", fill) is None
    assert recorded_answer(recorded, set(), "confirm", "Usunąć najem?", fill) is None
    assert recorded_answer([{"kind": "alert"}], set(), "alert", "Zapisano.", fill) == 0
