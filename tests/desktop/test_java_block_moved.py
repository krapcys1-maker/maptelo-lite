"""A block of records moved by one as the person goes on with Tab (Oracle Forms' lines: eight rows
shown, the ninth line typed into the last row's fields after the block moved up).

The program rewrites every field of the block at once. The bridge reads each field's text only when
it gets to the event, and in such a burst that is after the person typed the next item and its
quantity: the rewrite looked like the program writing them, and the typing was lost. The events
below are a Swing form's built that way, made shorter (benchmark D09).
"""

from __future__ import annotations

from typing import Any

from maptelo.capture.java import Interpreter

STATES = ["enabled", "showing", "visible", "focusable", "editable"]
CHAIN = [("internal frame", "Sales Orders"), ("frame", "Wiorek Applications")]
ITEM = (768, 648, 114, 20)
QTY = (1158, 648, 59, 20)
WAREHOUSE = (1693, 648, 81, 20)
OTHERS = [(f"0/0/{80 + n}", (240 + 60 * n, 648, 50, 20)) for n in range(6)]


def ev(
    kind: str,
    t: float,
    name: str,
    path: str,
    box: tuple[int, int, int, int],
    *,
    text: str | None = None,
    read: float | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "path": path,
        "role": "text",
        "name": name,
        "states": STATES,
        "box": list(box),
    }
    if text is not None:
        node["text"] = text
    out: dict[str, Any] = {
        "kind": kind,
        "t": t,
        "source": {"node": node, "chain": CHAIN, "window": 1},
    }
    if read is not None:
        out["read"] = read
    return out


def _block_moved(it: Interpreter, *, read: float, item: str = "31830-D", qty: str = "180") -> None:
    """The person in the last row's Warehouse; Tab: the block moved up, every field rewritten (the
    Warehouse with the focus still in it emptied), read only at ``read``, when the next item and
    its quantity were typed already."""
    it.feed(ev("focus", 33.0, "Warehouse List of Values", "0/0/97", WAREHOUSE, text="WRK-GDA"))
    for n, (path, box) in enumerate(OTHERS):
        it.feed(
            ev("text_changed", 35.30 + n * 0.002, f"Column {n}", path, box, text=str(n), read=read)
        )
    it.feed(
        ev(
            "text_changed",
            35.313,
            "Warehouse List of Values",
            "0/0/97",
            WAREHOUSE,
            text="",
            read=read,
        )
    )
    it.feed(
        ev(
            "text_changed",
            35.336,
            "Ordered Item RequiredList of Values",
            "0/0/89",
            ITEM,
            text=item,
            read=read,
        )
    )
    it.feed(ev("text_changed", 35.338, "Qty Required", "0/0/91", QTY, text=qty, read=read))


def test_the_next_line_typed_while_the_block_was_read_is_the_persons() -> None:
    it = Interpreter()
    _block_moved(it, read=36.20)
    # the focus came to the item before the typing; its text read late too, no change told after
    it.feed(
        ev(
            "focus",
            35.348,
            "Ordered Item RequiredList of Values",
            "0/0/89",
            ITEM,
            text="31830-D",
            read=36.21,
        )
    )
    it.feed(
        ev(
            "mouse_pressed",
            35.350,
            "Ordered Item RequiredList of Values",
            "0/0/89",
            ITEM,
            text="31830-D",
        )
    )
    it.feed(
        ev(
            "mouse_clicked",
            35.351,
            "Ordered Item RequiredList of Values",
            "0/0/89",
            ITEM,
            text="31830-D",
        )
    )
    # the form's answer to the item (its description, price), then the quantity's field
    for n, (path, box) in enumerate(OTHERS[:5]):
        it.feed(
            ev(
                "text_changed",
                36.068 + n * 0.001,
                f"Column {n}",
                path,
                box,
                text=f"x{n}",
                read=36.22,
            )
        )
    it.feed(ev("focus", 36.074, "Qty Required", "0/0/91", QTY, text="180", read=36.23))
    it.feed(ev("mouse_pressed", 36.076, "Qty Required", "0/0/91", QTY, text="180"))
    it.feed(ev("text_changed", 36.078, "Qty Required", "0/0/91", QTY, text="180", read=36.24))
    it.feed(ev("focus", 36.754, "Request Date Required", "0/0/94", (1371, 648, 114, 20), text=""))
    it.finish(37.0)
    assert [(a.type, a.seen.node.name if a.seen else None, a.value) for a in it.take()] == [
        ("fill", "Ordered Item RequiredList of Values", "31830-D"),
        ("fill", "Qty Required", "180"),
    ]


def test_the_field_with_the_focus_emptied_with_the_block_is_not_typed() -> None:
    """The Warehouse kept its value; the program emptied it with the rest of the block as the
    cursor went to the next record: no step „Warehouse” = ""."""
    it = Interpreter()
    _block_moved(it, read=35.35)
    it.feed(
        ev(
            "focus",
            35.348,
            "Ordered Item RequiredList of Values",
            "0/0/89",
            ITEM,
            text="",
            read=35.35,
        )
    )
    it.finish(36.0)
    assert [a for a in it.take() if a.seen and a.seen.node.name.startswith("Warehouse")] == []


def test_a_value_the_program_wrote_read_at_once_is_not_typed_by_a_click_in_the_field() -> None:
    """Read as it came, the program's write is what the field held: the person clicking in the
    field and going on typed nothing."""
    it = Interpreter()
    it.feed(
        ev(
            "text_changed",
            10.0,
            "Customer Line",
            "0/0/95",
            (1489, 648, 82, 20),
            text="7",
            read=10.001,
        )
    )
    it.feed(
        ev("focus", 11.0, "Customer Line", "0/0/95", (1489, 648, 82, 20), text="7", read=11.001)
    )
    it.feed(ev("mouse_pressed", 11.002, "Customer Line", "0/0/95", (1489, 648, 82, 20), text="7"))
    it.feed(ev("focus", 12.0, "Qty Required", "0/0/91", QTY, text=""))
    it.finish(13.0)
    assert it.take() == []


def test_on_the_persons_own_desktop_the_keys_that_write_tell_it() -> None:
    """Where the keys that write are read, a late text is the person's only if one went down."""
    for typed, acts in ((False, []), (True, [("fill", "31830-D")])):
        it = Interpreter(typing_read=True)
        it.feed({"kind": "key", "t": 30.0, "key": "Tab"})
        it.feed({"kind": "typed", "t": 30.5})
        _block_moved(it, read=36.20)
        it.feed(
            ev(
                "focus",
                35.348,
                "Ordered Item RequiredList of Values",
                "0/0/89",
                ITEM,
                text="31830-D",
                read=36.21,
            )
        )
        if typed:
            it.feed({"kind": "typed", "t": 35.6})
        it.feed({"kind": "key", "t": 36.0, "key": "Tab"})
        it.feed(ev("focus", 36.074, "Qty Required", "0/0/91", QTY, text="", read=36.23))
        it.finish(37.0)
        got = [(a.type, a.value) for a in it.take() if a.type == "fill"]
        assert got == acts, typed
