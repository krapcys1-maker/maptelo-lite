"""What the person gave in a window, written by the program into the field they came back to,
is the window's answer, not typing.

Oracle Forms writes a list of values' row, a calendar's day or an attributes window's segments
into the field a server's answer after the focus came back to it: the bridge tells a change of
the field with the focus, as typing is told (else: the row's value typed into the field, an
Enter after it; the attributes' summary „[ ]” filled as data). Reproduced on a Swing form that
answers so."""

from __future__ import annotations

from typing import Any

from maptelo.capture.java import Interpreter

FORM = [("internal frame", "Price Lists"), ("frame", "Oracle Applications")]
NAME = (212, 160, 200, 22)
CURRENCY = (212, 190, 80, 22)


def ev(
    kind: str,
    t: float,
    role: str,
    name: str,
    path: str,
    *,
    box: tuple[int, int, int, int] = (0, 0, 0, 0),
    text: str | None = None,
    window: int = 1,
    chain: list[tuple[str, str]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    node: dict[str, Any] = {"path": path, "role": role, "name": name, "box": list(box)}
    node["states"] = ["enabled", "showing", "visible", "focusable"]
    if text is not None:
        node["text"] = text
    source = {"node": node, "chain": FORM if chain is None else chain, "window": window}
    return {"kind": kind, "t": t, "source": source, **extra}


def pick_from_list(it: Interpreter, t: float, *, window: int, chain: list[tuple[str, str]]) -> None:
    """The person in the list: its table has the focus, a row is clicked, then OK."""
    table = "0/0/1/0/0/0/0"
    it.feed(ev("focus", t, "table", "Price Lists", table, window=window, chain=chain))
    it.feed(ev("active_descendant", t + 0.6, "table", "Price Lists", table, window=window,
               chain=chain, new={"role": "label", "name": "Wholesale", "index": 1}))  # fmt: skip
    for kind, at in (("mouse_pressed", t + 0.7), ("mouse_clicked", t + 0.71)):
        it.feed(ev(kind, at, "table", "Price Lists", table, window=window, chain=chain))
    ok = "0/0/0/1/0/1/0"
    it.feed(ev("mouse_pressed", t + 1.4, "push button", "OK", ok, window=window, chain=chain))
    it.feed(ev("mouse_clicked", t + 1.42, "push button", "OK", ok, window=window, chain=chain))


def back_in_name(it: Interpreter, t: float, written: str) -> None:
    """The focus back in „Name”, the program's write 150 ms later, the canvas's „…" moving,
    then Tab to „Currency”."""
    it.feed(ev("focus", t, "text", "Name", "0/0/1/0/1/0/0/1/0/0/1", box=NAME, text=""))
    it.feed(ev("text_changed", t + 0.15, "text", "Name", "0/0/1/0/1/0/0/1/0/0/1", box=NAME,
               text=written))  # fmt: skip
    moved = {"node": {"role": "panel", "name": ""}}  # the canvas's „…” moving
    it.feed({"kind": "child_changed", "t": t + 0.16, "source": moved})
    it.feed(ev("focus", t + 0.8, "text", "Currency", "0/0/1/0/1/0/0/1/0/0/2", box=CURRENCY,
               text=""))  # fmt: skip


def test_a_row_of_a_list_of_values_written_by_the_program_is_no_typing() -> None:
    it = Interpreter()
    dialog = [("dialog", "Price Lists"), ("frame", "Oracle Applications")]
    pick_from_list(it, 2.0, window=2, chain=dialog)
    back_in_name(it, 3.45, "Wholesale")
    it.tick(5.0)
    it.finish(5.0)
    assert [(a.type, a.cell, a.seen.node.name if a.seen else None) for a in it.take()] == [
        ("click", "Wholesale", "Price Lists"),
        ("click", None, "OK"),
    ]


def test_a_list_of_values_shown_as_a_frame_of_the_same_window_answers_too() -> None:
    """Oracle Forms shows its lists of values as frames inside the program's one window."""
    it = Interpreter()
    pick_from_list(it, 2.0, window=1, chain=[("internal frame", "Price Lists LOV"), *FORM[1:]])
    back_in_name(it, 3.45, "Wholesale")
    it.finish(5.0)
    assert [a.type for a in it.take()] == ["click", "click"]


def test_typing_after_a_list_closed_without_its_row_is_typing() -> None:
    """The list cancelled, then the person types into the field: the value is no row of it."""
    it = Interpreter()
    dialog = [("dialog", "Price Lists"), ("frame", "Oracle Applications")]
    pick_from_list(it, 2.0, window=2, chain=dialog)
    back_in_name(it, 3.45, "Corporate Europe")
    it.finish(5.0)
    assert [(a.type, a.value) for a in it.take()][-1] == ("fill", "Corporate Europe")


def test_the_segments_of_an_attributes_window_written_as_its_summary_are_no_typing() -> None:
    """„YES”, „YES”, „EUR” typed in the attributes window, OK: the program writes „YES.YES.EUR”
    into „Additional Information” once the focus is back there (the map typed the summary)."""
    it = Interpreter()
    dialog = [("dialog", "Additional Price List Information"), ("frame", "Oracle Applications")]
    info = (212, 310, 200, 22)
    t = 1.0
    for i, (name, value) in enumerate([("Rebate", "YES"), ("Accrual", "YES"), ("Region", "EUR")]):
        box = (468, 271 + 30 * i, 80, 22)
        path = f"0/0/1/0/0/{i + 1}"
        it.feed(ev("focus", t, "text", name, path, box=box, text="", window=2, chain=dialog))
        it.feed(ev("text_changed", t + 0.5, "text", name, path, box=box, text=value, window=2,
                   chain=dialog))  # fmt: skip
        t += 1.0
    ok = "0/0/1/0/0/4"
    it.feed(ev("mouse_pressed", t, "push button", "OK", ok, window=2, chain=dialog))
    it.feed(ev("mouse_clicked", t + 0.02, "push button", "OK", ok, window=2, chain=dialog))
    field = "0/0/1/0/1/0/0/1/0/0/6"
    it.feed(ev("focus", t + 0.03, "text", "Additional Information", field, box=info, text="[ ]"))
    it.feed(ev("text_changed", t + 0.18, "text", "Additional Information", field, box=info,
               text="YES.YES.EUR"))  # fmt: skip
    it.feed(ev("focus", t + 1.0, "text", "Description", "0/0/1/0/1/0/0/1/0/0/7",
               box=(212, 340, 260, 22), text=""))  # fmt: skip
    it.finish(t + 2.0)
    assert [(a.type, a.value) for a in it.take()] == [
        ("fill", "YES"),
        ("fill", "YES"),
        ("fill", "EUR"),
        ("click", None),
    ]


def test_a_day_of_a_calendar_written_into_its_date_field_is_no_typing() -> None:
    it = Interpreter()
    calendar = [("dialog", "Calendar"), ("frame", "Oracle Applications")]
    start = (212, 220, 110, 22)
    day = "0/0/1/0/0/13"
    it.feed(ev("mouse_pressed", 1.0, "push button", "14 November 2026", day, window=2,
               chain=calendar))  # fmt: skip
    it.feed(ev("mouse_clicked", 1.02, "push button", "14 November 2026", day, window=2,
               chain=calendar))  # fmt: skip
    field = "0/0/1/0/1/0/0/1/0/0/3"
    it.feed(ev("focus", 1.05, "text", "Start Date", field, box=start, text=""))
    it.feed(ev("text_changed", 1.2, "text", "Start Date", field, box=start, text="14-NOV-2026"))
    it.feed(ev("focus", 2.0, "text", "End Date", "0/0/1/0/1/0/0/1/0/0/4",
               box=(342, 220, 110, 22), text=""))  # fmt: skip
    it.finish(3.0)
    assert [(a.type, a.seen.node.name if a.seen else None) for a in it.take()] == [
        ("click", "14 November 2026")
    ]


def test_a_list_oracle_opened_after_tab_writes_the_field_left_not_the_next_one() -> None:
    """„Ea” typed into „UOM”, Tab: Oracle finds two units (EA, Ea) and opens the list itself;
    the row chosen is written into „UOM”, while the focus is already in the next field or
    back in „UOM”. The typing is the step, and the list's row; no field gets the row's value
    as typed (the map had it under the next field)."""
    uom, value = (212, 430, 60, 22), (282, 430, 80, 22)
    dialog = [("dialog", "Units of Measure"), ("frame", "Oracle Applications")]
    table = "0/0/1/0/0/0/0"
    for back_in_uom in (False, True):
        it = Interpreter()
        it.feed(ev("focus", 1.0, "text", "UOM List Values: ", "0/0/1/7", box=uom, text=""))
        it.feed(ev("text_changed", 1.3, "text", "UOM List Values: Ea", "0/0/1/7", box=uom,
                   text="Ea"))  # fmt: skip
        it.feed(ev("focus", 1.6, "text", "Value", "0/0/1/8", box=value, text=""))  # Tab
        it.feed(ev("focus", 1.9, "table", "Units of Measure", table, window=2, chain=dialog))
        it.feed(ev("active_descendant", 2.4, "table", "Units of Measure", table, window=2,
                   chain=dialog, new={"role": "label", "name": "EA", "index": 0}))  # fmt: skip
        for kind, at in (("mouse_pressed", 2.5), ("mouse_clicked", 2.51)):
            it.feed(ev(kind, at, "table", "Units of Measure", table, window=2, chain=dialog))
        ok = "0/0/0/1/0/1/0"
        for kind, at in (("mouse_pressed", 3.0), ("mouse_clicked", 3.02)):
            it.feed(ev(kind, at, "push button", "OK", ok, window=2, chain=dialog))
        if back_in_uom:  # the navigation held: back in „UOM”, then Tab again
            it.feed(ev("focus", 3.05, "text", "UOM List Values: Ea", "0/0/1/7", box=uom,
                       text="Ea"))  # fmt: skip
        it.feed(ev("text_changed", 3.2, "text", "UOM List Values: EA", "0/0/1/7", box=uom,
                   text="EA"))  # fmt: skip
        it.feed(ev("focus", 3.8, "text", "Value", "0/0/1/8", box=value, text=""))
        it.finish(5.0)
        acts = [(a.type, a.value, a.cell, a.seen.node.name if a.seen else None) for a in it.take()]
        assert acts == [
            ("fill", "Ea", None, "UOM List Values: Ea"),
            ("click", None, "EA", "Units of Measure"),
            ("click", None, None, "OK"),
        ], back_in_uom
