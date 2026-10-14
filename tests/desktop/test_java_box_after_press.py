"""A combo box the program sets just after the person pressed a button, the box untouched, is the
program's answer to the button (benchmark M3 r5: Java's file chooser shows the chosen file's
folder in „Look In:” 50 ms after Open). It was a step of the map, „Open” lost its window, and the
chooser's way went to a person."""

from __future__ import annotations

from maptelo.capture.java import Interpreter
from tests.desktop.test_recording import ev

CHOOSER = [("dialog", "Otwórz plik cennika"), ("frame", "WCR")]
PATH = r"C:\Temp\m3\seed1\aneks_K0018_2026-12.csv"


def acts(box_at: float, *, touched: bool = False) -> list[tuple[str, str]]:
    it = Interpreter()
    it.feed(ev("focus", 1.0, "text", "File Name:", "0/1/2", chain=CHOOSER, text=""))
    it.feed(ev("text_changed", 1.2, "text", "File Name:", "0/1/2", chain=CHOOSER, text=PATH))
    if touched:
        it.feed(ev("mouse_clicked", box_at - 0.2, "combo box", "Look In:", "0/1/0", chain=CHOOSER))
    it.feed(ev("mouse_pressed", 3.29, "push button", "Open", "0/1/5", chain=CHOOSER))
    it.feed(ev("active_descendant", box_at, "combo box", "Look In:", "0/1/0", chain=CHOOSER,
               new={"role": "label", "name": "seed1"}))  # fmt: skip
    it.finish(5.0)
    return [(a.type, a.seen.node.name if a.seen else "") for a in it.take()]


def test_a_box_set_as_a_button_is_pressed_is_the_programs() -> None:
    assert acts(3.342) == [("fill", "File Name:"), ("click", "Open")]


def test_a_box_the_person_chose_is_a_step() -> None:
    """Changed long after the press, or touched by the person: a choice."""
    assert ("select", "Look In:") in acts(4.5)
    assert ("select", "Look In:") in acts(3.342, touched=True)
