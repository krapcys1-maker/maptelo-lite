"""A window that only says the work was done („Order 61001 has been booked.”, its one OK) after
a click: the click saved, the message tells of it; it is no window the save is made in
(benchmark D09: Book Order was taken for a click that only opened the Note, so nothing saved).
A refusal's message (one OK too) is no save."""

from __future__ import annotations

import pytest

from maptelo.mapping.build import _done_message
from maptelo.trace.schema import TraceState


@pytest.mark.parametrize(
    ("aria", "done"),
    [
        ('- dialog "Note"\n- text: Order 61001 has been booked.\n- button "OK"', True),
        ('- dialog "Informacja"\n- text: Nota została zapisana.\n- button "OK"', True),
        ('- dialog "Note"\n- text: APP-ONT-250304: Customer on hold.\n- button "OK"', False),
        ('- dialog "Pytanie"\n- text: Zapisano szkic. Zatwierdzić?\n- button "Tak"\n- button "Nie"',
         False),
        ('- dialog "Nowa"\n- text: Saved.\n- textbox "Uwagi"\n- button "OK"', False),
    ],
)  # fmt: skip
def test_a_message_that_the_work_was_done(aria: str, done: bool) -> None:
    state = TraceState(id="s001", t=1.0, url="java://program/Note", aria=aria, window=1)
    assert _done_message(state) is done
