"""A rate looked up for a day, then typed into the invoice: the day without quotations that a
person tried first is a refusal said in a status line, not the work; the rate is read in the
row of the table named by the invoice's currency from the sheet."""

from __future__ import annotations

from pathlib import Path

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo
from maptelo.trace.schema import DataRef, RowContext
from tests.mapping.test_many_apps import ERP, Recording, field, found_by_its_words

NBP = "http://kursy.test"
SHEET = (
    "Numer faktury;Waluta;Data wystawienia;Data wykonania usługi\n"
    "RE-2026-08907;EUR;2026-09-25;2026-09-21\n"
    "BDS-2026-0917;USD;2026-09-29;2026-09-26\n"
)


def rates(day: str, shown: bool) -> str:
    head = '- heading "Kursy średnie walut" [level=1]\n'
    if not shown:
        return head + f"- status: Brak tabeli z dnia {day} (dzień bez notowań).\n"
    return head + (
        f'- table "Tabela 187/A/NBP/2026 z dnia {day}":\n'
        '  - row "Waluta Kod Kurs średni":\n'
        '    - columnheader "Waluta"\n    - columnheader "Kod"\n    - columnheader "Kurs średni"\n'
        '  - row "euro EUR 4,3885":\n'
        '    - cell "euro"\n    - cell "EUR"\n    - cell "4,3885"\n'
        '  - row "dolar amerykański USD 3,8262":\n'
        '    - cell "dolar amerykański"\n    - cell "USD"\n    - cell "3,8262"\n'
    )


def looked_up(days: list[str], tmp_path: Path) -> Recording:
    r = Recording()
    start = r.state(f"{NBP}/", rates(days[0], True))
    r.add("navigate", f"{NBP}/", value=f"{NBP}/", state_after=start)
    show = found_by_its_words(ElementInfo(tag="button", role="button", name="Pokaż"))
    before = start
    for n, day in enumerate(days):
        last = n == len(days) - 1
        after = r.state(f"{NBP}/tabela?day={day}", rates(day, last))
        r.add("fill", f"{NBP}/", target=field("Data"), value=day, state_before=before)
        r.add("click", f"{NBP}/", target=show, state_before=before, state_after=after)
        if not last:
            told = ElementInfo(
                tag="div", role="status", text=f"Brak tabeli z dnia {day} (dzień bez notowań)."
            )
            r.add("appeared", f"{NBP}/", target=told, state_before=before, state_after=after)
        before = after
    listed = f"{ERP}/faktury-walutowe"
    table = r.state(
        listed, '- table "Faktury":\n  - row "BDS-2026-0917":\n    - cell "BDS-2026-0917"\n'
    )
    r.add("navigate", listed, value=listed, state_before=before, state_after=table)
    invoice = found_by_its_words(
        ElementInfo(
            tag="a",
            role="link",
            name="BDS-2026-0917",
            row=RowContext(table="Faktury", cells={"Numer faktury": "BDS-2026-0917"}),
        )
    )
    form = r.state(f"{listed}/4", '- heading "Faktura zakupu w walucie" [level=1]\n')
    r.add("click", listed, target=invoice, state_before=table, state_after=form)
    r.add("fill", f"{listed}/4", target=field("Kurs średni NBP"), value="3,8262", state_before=form)
    (tmp_path / "faktury.csv").write_text(SHEET, encoding="utf-8")
    return r


def test_the_days_without_a_table_tried_first_are_refusals_not_the_work(tmp_path: Path) -> None:
    r = looked_up(["2026-09-27", "2026-09-26", "2026-09-25"], tmp_path)
    model = map_trace(r.trace(tmp_path / "trace.jsonl", DataRef(file="faktury.csv"))).model
    fills = [s for s in model.steps if s.action.value == "fill" and s.value == "$inputs.data"]
    assert len(fills) == 1
    assert model.inputs["data"].example == "2026-09-25"  # the day the table showed
    click = next(s for s in model.steps if s.action.value == "click")
    assert click.outcomes is not None
    refused = next(k for k in click.outcomes if k != "done")
    assert model.exceptions[refused].kind.value == "business"


def test_the_rate_is_read_in_the_row_of_the_invoices_currency(tmp_path: Path) -> None:
    r = looked_up(["2026-09-25"], tmp_path)
    model = map_trace(r.trace(tmp_path / "trace.jsonl", DataRef(file="faktury.csv"))).model
    read = next(s for s in model.steps if s.action.value == "read" and s.within is not None)
    assert read.within is not None
    assert read.within.where == {"Kod": "$inputs.waluta"}
    assert model.inputs["waluta"].column == "Waluta"
    typed = next(s for s in model.steps if s.intent.endswith("„Kurs średni NBP”"))
    assert typed.value == f"$vars.{read.save_as}"


def test_a_line_added_and_another_after_it_is_no_refusal() -> None:
    r = Recording()
    url = f"{ERP}/zamowienia/7"
    form = r.state(url, '- heading "Zamówienie" [level=1]\n- textbox "Ilość"\n')
    r.add("navigate", url, value=url, state_after=form)
    add = found_by_its_words(ElementInfo(tag="button", role="button", name="Dodaj"))
    for count in ("5", "7"):
        after = r.state(url, '- heading "Zamówienie" [level=1]\n- status: Dodano pozycję.\n')
        r.add("fill", url, target=field("Ilość"), value=count, state_before=form)
        r.add("click", url, target=add, state_before=form, state_after=after, sent=["POST /z"])
        told = ElementInfo(tag="div", role="status", text="Dodano pozycję.")
        r.add("appeared", url, target=told, state_before=form, state_after=after)
    model = map_trace(r.trace()).model
    assert not model.exceptions
