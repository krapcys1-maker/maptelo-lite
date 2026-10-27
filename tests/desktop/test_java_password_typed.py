"""A password typed into a Java program's password field is a step of the recording, though
the bridge reads such a field as a secret whatever it holds (empty or not): the step keeps no
value, only that a secret was typed."""

from __future__ import annotations

from maptelo.capture.java import Interpreter
from maptelo.desktop.screen import SECRET
from tests.desktop.test_recording import ev


def test_a_password_typed_into_a_field_seen_before_is_a_secret_step() -> None:
    it = Interpreter()
    it.remember(1, {"0/2": SECRET}, 0.5)  # the screen before: the field reads as a secret
    it.feed(ev("focus", 1.0, "password text", "Hasło", "0/2", text=SECRET))
    for n, at in enumerate((1.2, 1.9, 2.6, 3.3)):  # typed slowly, one key at a time
        it.feed(ev("text_changed", at, "password text", "Hasło", "0/2", text=SECRET, n=n))
    it.feed(ev("focus", 4.0, "text", "Uwagi", "0/3", text=""))
    it.finish(5.0)
    fills = [a for a in it.take() if a.type == "fill"]
    assert [(a.seen.node.name, a.secret, a.value) for a in fills if a.seen] == [
        ("Hasło", True, None)
    ]
