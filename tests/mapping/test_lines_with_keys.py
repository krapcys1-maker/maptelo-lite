"""The lines of a record typed one after another, with an Enter between some fields of one line
and not another (a program's form whose delay swallowed a key, benchmark D08): the lines are one
block done for each line all the same, and no line's value is left outside it."""

from __future__ import annotations

from maptelo.mapping import map_trace
from tests.mapping.test_many_apps import ERP, Recording, field

URL = f"{ERP}/cennik/1"
FORM = '- textbox "Grouping"\n- textbox "Context"\n- textbox "Value"\n- button "Zapisz"\n'


def test_lines_with_an_enter_here_and_not_there_are_one_block() -> None:
    r = Recording()
    form = r.state(URL, FORM)
    r.add("navigate", URL, value=URL, state_after=form)
    lines = [("1", "Order", "K0010", ("Context",)), ("2", "Item", "48212-B", ("Value",)),
             ("3", "Order", "K0020", ())]  # fmt: skip
    for grouping, context, value, enter_after in lines:
        for label, typed in (("Grouping", grouping), ("Context", context), ("Value", value)):
            r.add("fill", URL, target=field(label), value=typed, state_before=form)
            if label in enter_after:
                r.add("press", URL, target=field(label), value="Enter", state_before=form)
    save = field("Zapisz")
    r.add("click", URL, target=save, state_before=form, state_after=form, sent=["POST /c"])
    model = map_trace(r.trace(), sheet=False).model  # a broken model would not validate
    fills = [s for s in model.steps if s.action.value == "fill"]
    assert [s.target[0].name for s in fills] == ["Grouping", "Context", "Value"]
    assert all(s.per_line for s in fills)
