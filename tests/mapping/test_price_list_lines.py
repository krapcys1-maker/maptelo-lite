"""One recording of a price list in a program built like Oracle Forms, with the sheet of its
two lines (Wiórek's synthetic data): the header typed once (the name the sheet holds,
„Account ” and the account, the order's number after „_ZK_” of the name, a date the CSV file
writes as Excel's number), three rows of
qualifiers with values of their own, and two lines, each from its row of the sheet, the item
chosen in a list of values whose options read „<item> dla <account> - <customer>”."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maptelo.mapping import map_trace
from maptelo.model.schema import ProcessModel
from maptelo.trace import ElementInfo, Trace, TraceEvent, TraceHeader, TraceState
from maptelo.trace.schema import DataRef, RowContext

APP = "java://oracle-applications"
FORM, LOV = f"{APP}/Price Lists", f"{APP}/Items"
HEADER = ("Name", "Description", "Order Number", "Start Date")
QUALIFIERS = ("Qualifier Context", "Qualifier Attribute", "Value From")
LINES = ("Product Value", "Value", "Start Date")
SHEET = (
    "Nazwa cennika;Konto;Indeks;Cena;Od\n"
    "WRK_ZK_5510;604217359.0;26386-F;6.04;46327\n"
    "WRK_ZK_5510;604217359.0;31830-D;5.30;46327\n"
)
"""As a program writes a sheet into a CSV file: the account as 604217359.0, the day
2026-11-01 as Excel's number 46327."""
CUSTOMER = "Hurtownia Wiórek"


def _quoted(value: str) -> str:
    return value if value else '""'


def _table(columns: tuple[str, ...], rows: list[list[str]], indent: str) -> list[str]:
    out = [f"{indent}- table:", f"{indent}  - row:"]
    out += [f'{indent}    - columnheader "{column}"' for column in columns]
    for row in rows:
        out.append(f"{indent}  - row:")
        for value in row:
            out += [f"{indent}    - cell:", f"{indent}      - textbox: {_quoted(value)}"]
    return out


class PriceList:
    """The person at the program: each call is what they did, the screen as it was then."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self.states: dict[str, TraceState] = {}
        self.header = dict.fromkeys(HEADER, "")
        self.qualifiers = [["", "", ""] for _ in range(6)]
        self.lines = [["", "", ""] for _ in range(4)]
        self.tab = "Qualifiers"
        self.lov: list[str] | None = None
        self.chosen: str | None = None

    def screen(self) -> str:
        if self.lov is not None:
            options = "\n".join(f'  - option "{o}"' for o in self.lov)
            return f'- dialog "Items":\n  - listbox "Items":\n{options}\n  - button "OK"'
        lines = ['- region "Price Lists":']
        for name, value in self.header.items():
            lines += [f"  - text: {name}", f'  - textbox "{name}": {_quoted(value)}']
        lines.append('  - tablist "Lines"')
        for tab in ("Qualifiers", "List Lines"):
            lines.append(f'  - tab "{tab}"' + (" [selected]" if tab == self.tab else ""))
        if self.tab == "Qualifiers":
            lines += _table(QUALIFIERS, self.qualifiers, "  ")
        else:
            lines += _table(LINES, self.lines, "  ")
        return "\n".join(lines)

    def state(self) -> str:
        state_id = f"s{len(self.states) + 1}"
        url, window = (LOV, 1) if self.lov is not None else (FORM, 0)
        self.states[state_id] = TraceState(
            id=state_id, t=len(self.events), url=url, aria=self.screen(), window=window
        )
        return state_id

    def act(self, kind: str, target: ElementInfo, value: str | None = None) -> None:
        before = self.state()
        url, window = (LOV, 1) if self.lov is not None else (FORM, 0)
        self.change(target, value)
        after = self.state()
        number = len(self.events) + 1
        self.events.append(
            TraceEvent(
                seq=number,
                t=number,
                type=kind,  # type: ignore[arg-type]
                url=url,
                target=target,
                value=value,
                window=window,
                state_before=before,
                state_after=after,
            )
        )

    def change(self, target: ElementInfo, value: str | None) -> None:
        """What the program shows after the act."""
        if target.role == "option" and self.lov is not None:
            self.chosen = target.name
        elif target.name == "OK" and self.lov is not None:
            self.lov = None
            item = (self.chosen or "").split(" dla ")[0]
            row = next(r for r in self.lines if r[0].endswith("%"))
            row[0] = item
        elif target.role == "tab":
            self.tab = target.name or self.tab
        elif target.row is not None and target.column and value is not None:
            rows, columns = (
                (self.qualifiers, QUALIFIERS) if self.tab == "Qualifiers" else (self.lines, LINES)
            )
            index = target.row.index or 0
            rows[index][columns.index(target.column)] = value
            if target.column == "Product Value" and value.endswith("%"):
                self.lov = [
                    f"{item} dla 604217359 - {CUSTOMER}" for item in ("26386-F", "31830-D")
                ] + ["26386-F dla 400100200 - Inny klient"]
        elif target.name in self.header and value is not None:
            self.header[target.name] = value

    def field(self, name: str) -> ElementInfo:
        return ElementInfo(
            tag="java:text",
            role="textbox",
            name=name,
            label=name,
            dialog="Price Lists",
            candidates=[{"role": "textbox", "name": name}, {"label": name}],  # type: ignore[list-item]
        )

    def cell(self, column: str, index: int) -> ElementInfo:
        rows, columns = (
            (self.qualifiers, QUALIFIERS) if self.tab == "Qualifiers" else (self.lines, LINES)
        )
        cells = dict(zip(columns, rows[index], strict=True))
        return ElementInfo(
            tag="java:text",
            role="textbox",
            name=column,
            label=column,
            dialog="Price Lists",
            column=column,
            row=RowContext(cells=cells, index=index),
            candidates=[  # type: ignore[list-item]
                {"role": "textbox", "name": column, "column": column},
                {"role": "textbox", "name": column},
                {"label": column},
            ],
        )

    def click(self, role: str, name: str, dialog: str | None = None, **more: Any) -> None:
        target = ElementInfo(
            tag=f"java:{role}",
            role=role,
            name=name,
            dialog=dialog,
            candidates=[{"role": role, "name": name}],  # type: ignore[list-item]
            **more,
        )
        self.act("click", target)

    def trace(self, folder: Path) -> Trace:
        (folder / "cennik.csv").write_text(SHEET, "utf-8")
        header = TraceHeader(
            recording_id="cennik",
            started_at=datetime(2026, 10, 19, tzinfo=UTC),
            start_url=f"{APP}/",
            data=DataRef(file="cennik.csv"),
            program="Oracle Applications",
        )
        return Trace(
            header=header, events=self.events, states=self.states, path=folder / "trace.jsonl"
        )


def recorded(qualifiers: list[tuple[str, str, str]] | None = None) -> PriceList:
    person = PriceList()
    person.act("fill", person.field("Name"), "WRK_ZK_5510")
    person.act("fill", person.field("Description"), "Account 604217359")
    person.act("fill", person.field("Order Number"), "5510")
    person.act("fill", person.field("Start Date"), "01-NOV-2026")
    rows = qualifiers or [
        ("Customer", "Ship To", "604217359"),
        ("Customer", "Bill To", "604217359"),
        ("Order", "Order Type", "Standard"),
    ]
    for index, row in enumerate(rows):
        for column, value in zip(QUALIFIERS, row, strict=True):
            person.act("fill", person.cell(column, index), value)
    person.click("tab", "List Lines", "Price Lists")
    for index, (item, price) in enumerate((("26386-F", "6.04"), ("31830-D", "5.30"))):
        person.act("fill", person.cell("Product Value", index), item.split("-")[0] + "%")
        person.click("option", f"{item} dla 604217359 - {CUSTOMER}", "Items")
        person.click("button", "OK", "Items")
        person.act("fill", person.cell("Value", index), price)
        person.act("fill", person.cell("Start Date", index), "01-NOV-2026")
    person.click("menuitem", "Save", text="File > Save", column="File")
    return person


def mapped(tmp_path: Path, person: PriceList | None = None) -> ProcessModel:
    return map_trace((person or recorded()).trace(tmp_path)).model


def by_description(model: ProcessModel, words: str) -> str:
    return next(name for name, spec in model.inputs.items() if spec.description == words)


def test_the_header_is_bound_to_its_columns_whatever_the_form(tmp_path: Path) -> None:
    model = mapped(tmp_path)
    name = model.inputs[by_description(model, "Name")]
    assert (name.column, name.per_line) == ("Nazwa cennika", False)
    account = model.inputs[by_description(model, "Description")]
    assert (account.column, account.typed_as) == ("Konto", "Account {}")
    order = model.inputs[by_description(model, "Order Number")]
    assert (order.column, order.taken_after) == ("Nazwa cennika", "_ZK_")
    assert order.coerce("WRK_ZK_5577") == "5577"
    day = model.inputs[by_description(model, "Start Date")]
    assert (day.column, day.type.value, day.example) == ("Od", "date", "2026-11-01")
    assert (day.written_as, day.typed_as, day.per_line) == ("excel", "DD-MON-YYYY", False)


def test_each_row_of_the_qualifiers_has_its_own_inputs(tmp_path: Path) -> None:
    model = mapped(tmp_path)
    contexts = [
        model.inputs[by_description(model, f"Qualifier Context (wiersz {n})")] for n in (1, 2, 3)
    ]
    assert [c.example for c in contexts] == ["Customer", "Customer", "Order"]
    values = [model.inputs[by_description(model, f"Value From (wiersz {n})")] for n in (1, 2, 3)]
    assert [v.example for v in values] == ["604217359", "604217359", "Standard"]
    assert [v.column for v in values] == ["Konto", "Konto", None]
    typed = [
        step.value
        for step in model.steps
        if step.action.value == "fill" and step.target and step.target[0].name == "Value From"
    ]
    assert len(set(typed)) == len(typed) == 3  # no step is folded into another
    rows = [
        (step.within.where if step.within else {})
        for step in model.steps
        if step.target and step.target[0].name == "Qualifier Attribute"
    ]
    context = [by_description(model, f"Qualifier Context (wiersz {n})") for n in (1, 2, 3)]
    assert rows[1] == {"Qualifier Context": f"$inputs.{context[1]}", "Qualifier Attribute": None}
    assert rows[2] == {"Qualifier Context": f"$inputs.{context[2]}"}


def test_the_lines_are_one_block_done_per_line(tmp_path: Path) -> None:
    model = mapped(tmp_path)
    looped = [step for step in model.steps if step.per_line]
    assert [step.action.value for step in looped] == ["fill", "click", "click", "fill", "fill"]
    assert len(model.steps) == 1 + 4 + 9 + 1 + 5 + 1
    lines = {name: spec for name, spec in model.inputs.items() if spec.per_line}
    assert {spec.column for spec in lines.values()} == {"Indeks", "Cena", "Od"}
    assert model.records is not None
    assert set(model.records.one_run_per) == {"Nazwa cennika", "Konto", "Od"}


def test_the_list_of_values_is_chosen_by_the_records_values(tmp_path: Path) -> None:
    model = mapped(tmp_path)
    pick = next(step for step in model.steps if step.target and step.target[0].role == "option")
    assert pick.target is not None
    rung = pick.target[0]
    assert rung.name is not None
    item, account = re.findall(r"\{inputs\.(\w+)\}", rung.name)
    assert rung.name == "{...}{inputs." + item + "}{...}{inputs." + account + "}{...}"
    assert (model.inputs[item].column, model.inputs[item].per_line) == ("Indeks", True)
    assert (model.inputs[account].column, model.inputs[account].per_line) == ("Konto", False)
    assert pick.intent == "W oknie „Items” wybierz pozycję zawierającą „Indeks” i „Konto”"
    assert CUSTOMER not in rung.name
    before = model.steps[model.steps.index(pick) - 1]
    assert before.expect is None  # not the option of this record's item, by its words
    item_input = model.inputs[by_description(model, "Product Value")]
    assert (item_input.column, item_input.typed_as) == ("Indeks", "{}%")


def test_the_rows_of_one_table_alone_are_not_lines(tmp_path: Path) -> None:
    """The qualifiers typed in more rows than the lines cover: still no block per line."""
    rows = [("Customer", f"Site {n}", "604217359") for n in range(1, 6)]
    model = mapped(tmp_path, recorded(rows))
    looped = [step for step in model.steps if step.per_line]
    assert len(looped) == 5
    assert all(not (step.target and step.target[0].name == "Qualifier Context") for step in looped)
