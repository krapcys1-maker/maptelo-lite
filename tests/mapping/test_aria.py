from __future__ import annotations

from maptelo.trace.aria import messages, parse_aria, table_rows

SNAPSHOT = """- banner:
  - text: MiniERP Pricing demo
  - button "Sign out"
- main:
  - heading "48212-B Shelf-ready tray" [level=1]
  - paragraph: "Several versions: pick one"
  - status: Price saved (version V4).
  - table "Price versions":
    - caption: Price versions
    - rowgroup:
      - row "Version Status":
        - columnheader "Version"
        - columnheader "Status"
        - columnheader
    - rowgroup:
      - row "V1 Expired Select":
        - cell "V1"
        - cell "Expired"
        - cell "Select":
          - link "Select":
            - /url: "?version=2"
      - row "V2 Active Select":
        - cell "V2"
        - cell "Active"
        - cell "Select":
          - link "Select":
            - /url: "?version=3"
  - textbox "Say \\"hi\\"": typed value
"""


def test_tree_structure_and_attributes() -> None:
    root = parse_aria(SNAPSHOT)
    heading = root.find("heading")
    assert heading is not None
    assert heading.name == "48212-B Shelf-ready tray"
    assert heading.attrs == {"level": "1"}
    paragraph = root.find("paragraph")
    assert paragraph is not None
    assert paragraph.value == "Several versions: pick one"  # quotes removed
    textbox = root.find("textbox")
    assert textbox is not None
    assert textbox.name == 'Say "hi"'
    assert textbox.value == "typed value"
    assert len(root.find_all("link")) == 2


def test_table_rows_use_headers_and_number_unnamed_columns() -> None:
    table = parse_aria(SNAPSHOT).find("table", "Price versions")
    assert table is not None
    assert table_rows(table) == [
        {"Version": "V1", "Status": "Expired", "#3": "Select"},
        {"Version": "V2", "Status": "Active", "#3": "Select"},
    ]


def test_messages_and_text() -> None:
    root = parse_aria(SNAPSHOT)
    assert messages(root) == [("status", "Price saved (version V4).")]
    cell = root.find("cell", "Select")
    assert cell is not None
    assert cell.text() == "Select"


def test_unknown_lines_are_skipped() -> None:
    root = parse_aria('not a snapshot line\n- button "OK"\n')
    assert [n.role for n in root.children] == ["button"]
