# ruff: noqa: RUF001, RUF002
"""A recording made in a Java program (the benchmark's SRK, a Swing billing program)
mapped by the same code as a browser recording."""

from __future__ import annotations

from pathlib import Path

import pytest

from maptelo.mapping import map_trace
from maptelo.model.schema import Action, RiskClass
from maptelo.trace import load_trace

FIXTURE = Path(__file__).parents[1] / "fixtures" / "java" / "srk_wniosek_cenowy"


def test_a_java_recording_is_a_java_process() -> None:
    model = map_trace(load_trace(FIXTURE), lang="en").model
    assert model.application.kind == "java"
    assert model.application.window == "SRK"
    assert model.application.name == "SRK"


def test_its_steps_are_the_person_s() -> None:
    steps = map_trace(load_trace(FIXTURE), lang="en").model.steps
    acts = [(s.action, (s.target or [None])[0]) for s in steps]
    kinds = [a for a, _ in acts]
    assert kinds.count(Action.FILL) == 5
    assert Action.SELECT_OPTION in kinds
    menu = next(t for a, t in acts if t is not None and t.role == "menuitem")
    assert (menu.name, menu.column) == ("Cennik klienta", "Ceny")  # the item in its menu
    enters = [s for s in steps if s.action is Action.PRESS]
    assert [s.value for s in enters] == ["Enter", "Enter"]
    answer = steps[-1]
    assert answer.target is not None
    assert answer.target[0].name == "Tak"
    assert answer.window >= 1  # the question: a window over the main one


def test_its_screens_are_named_as_its_windows_are() -> None:
    """A Java screen is its frame or window as its title names it, the main window the program
    (the Lite test of 12.10: „W osobnym oknie „Kontrahent””, the first field of „Nowa wersja
    ceny – K0010”, and „Otwórz ekran „/”” with „adres `/`” as the first step)."""
    from maptelo.export import render_sop

    model = map_trace(load_trace(FIXTURE), lang="pl").model
    first = model.steps[0]
    assert first.intent == "Otwórz program „SRK”"
    names = {state.url: state.description for state in model.states.values()}
    assert names["/"] == "SRK"
    assert names["/Cennik klienta"] == "Cennik klienta"
    menu = next(s for s in model.steps if s.target and s.target[0].role == "menuitem")
    assert menu.intent == "Wybierz z menu „Ceny” pozycję „Cennik klienta”"
    dialog = next(url for url in names if url.startswith("/Nowa wersja ceny"))
    assert names[dialog] == "Nowa wersja ceny"  # the customer's code in its title left out
    sop = render_sop(model, lang="pl")
    assert "adres `/`" not in sop
    assert "W osobnym oknie „Nowa wersja ceny”" in sop
    assert "*”" not in sop
    # the robot checks each window it clicks in is open; a document shows it only for the
    # window that comes after a step (the question after saving), not for the one worked in
    assert sum(1 for step in model.steps if step.when is not None) == 3
    assert [line for line in sop.splitlines() if "Warunek:" in line] == [
        "   - Warunek: pojawia się okno „SRK – pytanie”"
    ]
    # the last step closes the question, and no steps come after it in the window below
    assert model.steps[-1].closes_window
    closing = [step for step in model.steps[:-1] if step.closes_window]
    assert sop.count("kolejne kroki wykonuje się w oknie poniżej") == len(closing)
    assert "   - Zamyka okno\n" in sop


def test_a_yes_told_in_the_window_under_its_question_is_the_question_s() -> None:
    """The bridge may tell the click on „Tak” in the window under the question, the only one
    open once the question had closed (the clean-Windows Lite test of 12.10: „Kliknij „Tak””,
    and no step marked as saving): the screen read before the click is the question, so the
    step is the question's, as when the recorder tells it at once."""
    told = map_trace(load_trace(FIXTURE), lang="pl").model.steps[-1]
    trace = load_trace(FIXTURE)
    late, main = trace.events[-1], trace.events[0]
    assert late.target is not None
    assert late.target.name == "Tak"
    late.url, late.title, late.window = main.url, main.title, 0
    late.target.dialog = None
    step = map_trace(trace, lang="pl").model.steps[-1]
    assert step.intent == told.intent == "W oknie „SRK – pytanie” kliknij „Tak”"
    assert step.effective_risk is told.effective_risk is RiskClass.COMMIT
    assert step.in_state == told.in_state
    assert step.window == 2  # the question's depth when it was read: over „Nowa wersja ceny”


STARTS_ON_A_NAVIGATOR = """
schema_version: '0.1'
id: price_list_update
version: 1
title: Price list update
application: {name: Wiorek Applications, kind: KIND, window: Wiorek Applications, base_url: BASE}
inputs:
  name: {type: string, description: Name, example: WRK-K0010-2026}
states:
  navigator: {description: Navigator - Pricing Manager, url: /Navigator - Pricing Manager}
  find: {description: Find Price Lists, url: /Find Price Lists}
steps:
  - id: open
    intent: Open the “Wiorek Applications” program
    action: navigate
    value: /
  - id: navigator_open
    intent: In the “Navigator - Pricing Manager” window, click “Open”
    action: click
    target: [{role: button, name: Open}]
    in_state: navigator
    when: {visible: {role: dialog, name: Navigator - Pricing Manager}}
  - id: enter_name
    intent: Fill in the “Name” field
    action: fill
    target: [{role: textbox, name: Name}]
    value: $inputs.name
    in_state: find
  - id: find
    intent: In the “Find Price Lists” window, click “Find”
    action: click
    target: [{role: button, name: Find}]
    in_state: find
    when: {visible: {role: dialog, name: Find Price Lists}}
"""


def test_the_window_a_java_program_starts_on_is_no_decision_in_documents() -> None:
    """The robot checks that the window it clicks in is open, also the navigator a Java
    program starts on; documents leave that check out for the first click after „Open the
    program” (the Lite film of 12.10 drew „the “Navigator - Pricing Manager” window
    appears?” there, a branch no recording had). In a browser application a window right
    after the first page keeps its condition: it may come only sometimes."""
    from maptelo.export import render_sop, render_svg
    from maptelo.export.describe import documented
    from maptelo.model.loader import parse_model

    java = STARTS_ON_A_NAVIGATOR.replace("KIND", "java").replace("BASE", "java://wiorek")
    model = parse_model(java)
    assert [s.id for s in model.steps if s.when is not None] == ["navigator_open", "find"]
    assert not [s.id for s in documented(model).steps if s.when is not None]
    assert "Only if:" not in render_sop(model, lang="en")
    assert "appears?" not in render_svg(model, lang="en")

    web = STARTS_ON_A_NAVIGATOR.replace("KIND", "web").replace("BASE", "http://wiorek.test")
    kept = [s.id for s in documented(parse_model(web)).steps if s.when is not None]
    assert kept == ["navigator_open"]


def test_amounts_are_typed_as_people_type_them() -> None:
    model = map_trace(load_trace(FIXTURE), lang="en").model
    price = next(spec for name, spec in model.inputs.items() if "cena" in name)
    assert price.typed_as == "0,00"


def test_table_checkbox_keeps_column_and_record_scope():
    from maptelo.trace import ElementInfo
    from maptelo.trace.schema import RowContext
    from tests.mapping.test_many_apps import Recording, field

    r = Recording()
    url = "java://srk/Invoice"
    screen = r.state(url, '- textbox "WZ"\n- table "Documents"\n')
    r.add("navigate", url, value=url, state_after=screen)
    r.add("fill", url, target=field("WZ"), value="WZ/42", state_before=screen)
    r.add(
        "check",
        url,
        state_before=screen,
        state_after=screen,
        target=ElementInfo(
            tag="java:table cell",
            role="cell",
            name="Invoice",
            column="Invoice",
            row=RowContext(table="Documents", cells={"Invoice": "", "WZ": "WZ/42"}),
        ),
    )
    model = map_trace(r.trace()).model
    step = next(s for s in model.steps if s.action is Action.CHECK)
    assert step.target[0].column == "Invoice"
    assert step.within.where == {"WZ": "$inputs.wz"}


@pytest.mark.parametrize("editor_table", ["Lines", None])
def test_opening_the_table_editor_is_part_of_filling_the_cell(editor_table):
    from maptelo.mapping.normalize import normalize
    from maptelo.trace import ElementInfo
    from maptelo.trace.schema import RowContext
    from tests.mapping.test_many_apps import Recording

    r = Recording()
    url = "java://srk/Correction"
    state = r.state(url, '- table "Lines"\n')
    target = ElementInfo(
        tag="java:table cell",
        role="cell",
        name="185",
        column="Quantity",
        row=RowContext(table="Lines", cells={"SKU": "ABC-1", "Quantity": "185"}),
    )
    r.add("click", url, target=target, state_before=state, state_after=state)
    r.add(
        "fill",
        url,
        target=target.model_copy(
            update={
                "name": "Quantity",
                "label": "Quantity",
                "row": target.row.model_copy(update={"table": editor_table}),
            }
        ),
        value="185",
        state_before=state,
        state_after=state,
    )
    assert [a.kind for a in normalize(r.trace()).steps] == ["fill"]


def test_a_row_picked_in_a_list_window_is_a_step_by_the_record_s_value() -> None:
    """Benchmark D05: the invoice searched for, then its row chosen and OK. Only the choice
    changes on the screen, yet it is no stray click: the row is the one whose number the
    record typed into the search."""
    from maptelo.trace import ElementInfo
    from maptelo.trace.schema import RowContext
    from tests.mapping.test_many_apps import Recording, field, found_by_its_words

    url = "java://srk/Wybor faktury"
    window = """- textbox "Szukaj": FV/2026/07/0045
- button "Znajdź"
- table "Faktury":
  - row:
    - columnheader "Nr"
    - columnheader "Brutto"
  - row:
    - cell: FV/2026/07/0045
    - cell: 18 496,63
- button "OK"
"""
    r = Recording()
    screen = r.state(url, window)
    r.add("navigate", url, value=url, state_after=screen)
    r.add("fill", url, target=field("Szukaj"), value="FV/2026/07/0045", state_before=screen)
    cell = ElementInfo(
        tag="java:table cell",
        role="cell",
        name="FV/2026/07/0045",
        text="FV/2026/07/0045",
        column="Nr",
        row=RowContext(table="Faktury", cells={"Nr": "FV/2026/07/0045", "Brutto": "18 496,63"}),
    )
    r.add("click", url, target=cell, state_before=screen, state_after=screen)
    ok = found_by_its_words(ElementInfo(tag="java:push button", role="button", name="OK"))
    r.add("click", url, target=ok, state_before=screen, state_after=screen)
    steps = map_trace(r.trace(), lang="en").model.steps
    picked = next(s for s in steps if s.within is not None)
    assert picked.within is not None
    assert picked.within.where == {"Nr": "$inputs.szukaj"}
    assert picked.target is not None
    assert (picked.target[0].role, picked.target[0].column) == ("cell", "Nr")
