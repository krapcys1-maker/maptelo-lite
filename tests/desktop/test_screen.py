"""A Java window's tree read as a person reads the screen (Oracle Forms and Swing names)."""

from __future__ import annotations

from maptelo.desktop.jab import Node
from maptelo.desktop.screen import build_screen, clean_name, fill_block_cells
from maptelo.trace.aria import parse_aria, table_rows


def node(path: str, role: str, name: str = "", *, y: int = 0, x: int = 0, **kw: object) -> Node:
    states = kw.pop("states", "enabled,focusable,visible,showing")
    box = kw.pop("box", (x, y, 100, 30))
    return Node(
        path=path,
        role=role,
        name=name,
        states=frozenset(str(states).split(",")),
        box=box,  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


def test_oracle_forms_names_are_read_as_people_read_them() -> None:
    assert clean_name("OK ALT O") == "OK"
    assert clean_name("Price Breaks alt B") == "Price Breaks"
    assert clean_name("Export mnemonic E") == "Export"
    assert clean_name("Main tab page Name Required") == "Name"
    assert clean_name("Lines tab page Lines tab page Supplier Item") == "Supplier Item"
    assert clean_name("Product Context RequiredList of Values") == "Product Context"
    assert clean_name("Category WymaganeLista wartości") == "Category"
    assert clean_name("CTC Compliance List Values: Yes") == "CTC Compliance"
    hint = (
        "Enter a partial value to limit the list, % to see all values.Warning: Entering % to "
        "see all values may take a very long time. Find"
    )
    assert clean_name(hint) == "Find"
    assert clean_name("null") == ""


def _price_list() -> list[Node]:
    """A form like Oracle's price list: a block of lines (fields alike, row under row), a list
    of values over it, a status bar."""
    nodes = [
        node("0", "frame", "Oracle Applications - TEST", box=(0, 0, 1000, 800)),
        node("0/0", "internal frame", "Price Lists", states="enabled,visible,showing,active"),
        node("0/0/0", "text", "Main tab page Name Required", y=50, text="LIST_PO_1"),
    ]
    for row, y in enumerate((200, 230, 260)):
        value = ["921399", "553100", ""][row]
        price = ["10.5", "7", ""][row]
        nodes.append(
            node(f"0/0/{1 + row}", "text", "Product Value Required", y=y, x=100, text=value)
        )
        nodes.append(node(f"0/0/{4 + row}", "text", "Value Required", y=y, x=300, text=price))
    nodes += [
        node("0/0/9", "internal frame", "Product Value", states="enabled,visible,showing,modal"),
        node("0/0/9/0", "text", "Find", y=400, text="%92"),
        node("0/0/9/1", "list", "", y=430),
        node(
            "0/0/9/1/0",
            "label",
            "Product Value:921399\tDescription:ITEM FOR 300",
            y=430,
            states="enabled,visible,showing,selected",
        ),
        node("0/0/9/2", "push button", "OK ALT O", y=500),
        node("0/1", "status bar", "", y=770),
        node("0/1/0", "label", "Record: 2/3", y=770),
        node("0/1/1", "label", "<OSC>", y=770),
    ]
    return nodes


def test_a_block_of_lines_is_a_table_of_its_fields() -> None:
    screen = build_screen("Oracle Applications - TEST", 1, _price_list())
    values = screen.find(role="textbox", name="Value")
    assert [e.row for e in values] == [0, 1, 2]
    assert values[0].cells == {"Product Value": "921399", "Value": "10.5"}
    assert values[0].column == "Value"
    table = parse_aria(screen.aria()).find("table")
    assert table is not None
    rows = table_rows(table)
    assert rows[0]["Product Value"] == "921399"


def test_a_field_named_as_a_column_elsewhere_is_not_a_row_of_it() -> None:
    """Oracle's price list has its own Start Date in its header, over the Start Date column of
    its lines: the lines are one block all the same (benchmark D06)."""
    nodes = [
        node("0", "frame", "Oracle Applications - TEST", box=(0, 0, 1000, 800)),
        node("0/0", "internal frame", "Price Lists", states="enabled,visible,showing,active"),
        node("0/0/0", "text", "Start Date", y=50, x=100, text="01-JAN-2026"),
    ]
    for row, y in enumerate((200, 230, 260)):
        item = ["921399", "", ""][row]
        nodes.append(node(f"0/0/{1 + row}", "text", "Product Value", y=y, x=100, text=item))
        start = ["01-JAN-2026", "", ""][row]
        nodes.append(node(f"0/0/{4 + row}", "text", "Start Date", y=y + 2, x=500, text=start))
    screen = build_screen("Oracle Applications - TEST", 1, nodes)
    starts = [e for e in screen.elements if e.name == "Start Date"]
    assert [e.block for e in starts].count(None) == 1  # the header's own
    lines = sorted((e for e in starts if e.block is not None), key=lambda e: e.row or 0)
    assert [e.row for e in lines] == [0, 1, 2]
    assert lines[0].cells == {"Product Value": "921399", "Start Date": "01-JAN-2026"}
    table = parse_aria(screen.aria()).find("table")
    assert table is not None
    assert len(table_rows(table)) == 3


def test_a_row_of_a_block_reads_its_fields_as_they_are() -> None:
    """A recording sets a field back to what it held before the act: its row says so too
    (benchmark D06: the new line's Product Value was empty before it was typed)."""
    screen = build_screen("Oracle Applications - TEST", 1, _price_list())
    first = next(e for e in screen.elements if e.name == "Product Value" and e.row == 0)
    first.value = ""
    fill_block_cells(screen.elements)
    price = next(e for e in screen.elements if e.name == "Value" and e.row == 0)
    assert price.cells == {"Product Value": "", "Value": "10.5"}


def test_a_list_of_values_over_the_form_is_where_the_person_works() -> None:
    screen = build_screen("Oracle Applications - TEST", 1, _price_list())
    assert screen.active_frame() == "Product Value"
    assert screen.modal_frames() == ["Product Value"]
    option = screen.find(role="option")[0]
    assert option.selected
    assert option.frame == "Product Value"
    assert screen.find(role="button", name="OK")[0].modal
    assert screen.status == ["Record: 2/3"]


def test_items_of_a_closed_menu_are_not_on_the_screen() -> None:
    nodes = [
        node("0", "frame", "App", box=(0, 0, 800, 600)),
        node("0/0", "menu bar"),
        node("0/0/0", "menu", "File ALT F"),
        node("0/0/0/0", "popup menu", "", states="enabled"),
        node("0/0/0/0/0", "menu item", "Export mnemonic E"),
    ]
    screen = build_screen("App", 1, nodes)
    assert [e.name for e in screen.elements if e.role == "menuitem"] == ["File"]


def test_the_wide_label_at_the_bottom_is_the_status_line() -> None:
    nodes = [
        node("0", "frame", "SRK", box=(0, 0, 1000, 800)),
        node("0/0", "label", "Pasek stanu", box=(0, 770, 900, 24), text="Zapisano wniosek"),
        node("0/1", "label", "Sesja", box=(900, 770, 100, 24), text=""),
        node("0/2", "label", "Kontrahent", box=(10, 100, 80, 24), text="Kontrahent"),
    ]
    screen = build_screen("SRK", 1, nodes)
    assert screen.status == ["Zapisano wniosek"]
    assert [e.value or e.node.text for e in screen.elements if e.role == "text"] == ["Kontrahent"]
