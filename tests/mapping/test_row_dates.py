"""Approve a day off with the button in its row (Odoo, benchmark p13): the sheet names the
employee and the first day (2026-10-28); Odoo lists the request with „28.10.2026 09:00:00”.
The row is the employee's request for that day, not any request of the employee's."""

from __future__ import annotations

from pathlib import Path

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo
from maptelo.trace.schema import DataRef, RowContext
from tests.mapping.test_many_apps import ERP, Recording, found_by_its_words

LIST = f"{ERP}/odoo/time-off"
HEAD = ("Pracownik", "Typ dni wolnych", "Data początkowa", "Status")
ROWS = [
    ("Dominik Mądrzak", "Urlop wypoczynkowy", "28.10.2026 09:00:00", "Do zatwierdzenia"),
    ("Dominik Mądrzak", "Urlop wypoczynkowy", "12.11.2026 09:00:00", "Do zatwierdzenia"),
    ("Adam Jośko", "Urlop wypoczynkowy", "04.11.2026 09:00:00", "Do zatwierdzenia"),
]


def listed() -> str:
    lines = ["- main:", '  - table "Dni wolne":', "    - rowgroup:", '      - row "head":']
    lines += [f'        - columnheader "{h}"' for h in HEAD]
    lines += ["    - rowgroup:"]
    for row in ROWS:
        lines += [f'      - row "{" ".join(row)}":']
        lines += [f'        - cell "{value}"' for value in row]
        lines += ['        - cell "Akceptuj":', '          - button "Akceptuj"']
    return "\n".join(lines) + "\n"


def test_the_request_is_the_employees_for_the_sheets_day(tmp_path: Path) -> None:
    (tmp_path / "wnioski.csv").write_text(
        "Pracownik;Od;Uwagi\nDominik Mądrzak;2026-10-28;\nAdam Jośko;2026-11-04;\n",
        encoding="utf-8",
    )
    r = Recording()
    shown = r.state(LIST, listed())
    r.add("navigate", LIST, value=LIST, state_after=shown)
    cells = {**dict(zip(HEAD, ROWS[0], strict=True)), "#5": "Akceptuj"}
    button = ElementInfo(
        tag="button", role="button", name="Akceptuj",
        row=RowContext(table="Dni wolne", cells=cells),
    )  # fmt: skip
    approve = "POST /web/dataset/call_button/hr.leave/action_approve"
    r.add("click", LIST, target=found_by_its_words(button), state_before=shown,
          state_after=shown, sent=[approve])  # fmt: skip
    trace = r.trace(tmp_path / "trace.jsonl", DataRef(file="wnioski.csv"))
    model = map_trace(trace).model
    row_step = next(s for s in model.steps if s.within is not None)
    assert row_step.within is not None
    assert row_step.within.where == {
        "Pracownik": "$inputs.pracownik",
        "Data początkowa": "$inputs.od",
    }
    assert model.inputs["od"].type.value == "date"
