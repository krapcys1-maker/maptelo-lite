"""Importuj unticked in each row of a negotiator's file that shows an error (benchmark M3). The
rows a person takes are the rows whose Błąd says something, and the next file has its errors in
other rows: one step done in each such row, not a step for each row of this file."""

from __future__ import annotations

from maptelo.mapping import map_trace
from maptelo.model.schema import Action, Step
from maptelo.trace import ElementInfo, TraceState
from maptelo.trace.locators import candidates_for
from maptelo.trace.schema import RowContext

from .test_normalize import Builder, element

FORM = "java://wcr/Import cennika"
ROWS = [  # Indeks, Cena, Błąd
    ("26386-F", "6.04", ""),
    ("31830-D", "5.30 zł", "Cena nie jest liczbą"),
    ("34631-D", "3.83", ""),
    ("11622-A", "0.92", "Indeks wycofany"),
]


def screen(rows: list[tuple[str, str, str]]) -> str:
    lines = ['- table "Wiersze pliku":', "  - row:"]
    lines += [f'    - columnheader "{h}"' for h in ("Importuj", "Indeks", "Cena", "Błąd")]
    for item, price, error in rows:
        lines += ["  - row:", "    - cell", f"    - cell: {item}", f"    - cell: {price}"]
        lines.append(f"    - cell: {error}" if error else "    - cell")
    return "\n".join([*lines, '- button "Importuj zaznaczone"']) + "\n"


def untick(rows: list[tuple[str, str, str]], index: int) -> ElementInfo:
    item, price, error = rows[index]
    cells = {"Importuj": "", "Indeks": item, "Cena": price, "Błąd": error}
    cell = ElementInfo(
        tag="java:table cell",
        role="cell",
        name="Importuj",
        text="Importuj",
        column="Importuj",
        dialog="Import cennika",
        row=RowContext(table="Wiersze pliku", cells=cells, index=index),
    )
    return cell.model_copy(update={"candidates": candidates_for(cell)})


def mapped(rows: list[tuple[str, str, str]], unticked: list[int]) -> list[Step]:
    b = Builder(start="java://wcr/")
    b.states["s1"] = TraceState(id="s1", t=1, url=FORM, aria=screen(rows))
    for index in unticked:
        b.add("uncheck", target=untick(rows, index), url=FORM, state_before="s1", state_after="s1")
    done = element("Importuj zaznaczone", tag="java:push button", dialog="Import cennika")
    done.candidates = candidates_for(done)
    b.add("click", target=done, url=FORM, state_before="s1", state_after="s1")
    return map_trace(b.trace()).model.steps


def test_a_box_unticked_in_every_row_with_an_error_is_one_step_done_in_each() -> None:
    steps = mapped(ROWS, [1, 3])
    unticked = [s for s in steps if s.action is Action.UNCHECK]
    assert len(unticked) == 1, [s.intent for s in steps]
    within = unticked[0].within
    assert within is not None
    assert within.pick == "each"
    assert within.where == {}
    assert within.where_not == {"Błąd": None}
    assert unticked[0].intent == (
        "Odznacz „Importuj” w każdym wierszu tabeli „Wiersze pliku”, w którym „Błąd” nie jest puste"
    )
    assert unticked[0].evidence is not None
    assert len(unticked[0].evidence.traces) == 2


def test_rows_that_are_not_every_row_with_an_error_stay_steps_of_their_own() -> None:
    """A third row with an error left ticked: the two rows were taken for something else."""
    rows = [*ROWS, ("70404-C", "2.25", "Data nie w formacie RRRR-MM-DD")]
    unticked = [s for s in mapped(rows, [1, 3]) if s.action is Action.UNCHECK]
    assert len(unticked) == 2
    assert all(s.within is not None and s.within.pick == "only" for s in unticked)


def test_one_unticked_row_is_no_rule_of_rows() -> None:
    unticked = [s for s in mapped(ROWS, [1]) if s.action is Action.UNCHECK]
    assert len(unticked) == 1
    assert unticked[0].within is not None
    assert unticked[0].within.pick == "only"
