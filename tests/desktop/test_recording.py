# ruff: noqa: RUF001
"""What a person did in a Java program, told from the Access Bridge's events (keys are not
among them: Enter is told by the screen reacting while the field keeps the focus)."""

from __future__ import annotations

from typing import Any

from maptelo.capture.java import (
    Interpreter,
    display_name,
    program_name,
    screen_url,
    title_template,
)

FRAME = [("internal frame", "Cennik klienta"), ("frame", "SRK 4.2.7")]
DIALOG = [("dialog", "Nowa wersja ceny – K0010"), ("frame", "SRK 4.2.7")]


def ev(
    kind: str,
    t: float,
    role: str,
    name: str,
    path: str,
    *,
    text: str | None = None,
    window: int = 1,
    chain: list[tuple[str, str]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    node = {"path": path, "role": role, "name": name, "states": ["enabled", "showing"]}
    if text is not None:
        node["text"] = text
    return {
        "kind": kind,
        "t": t,
        "source": {"node": node, "chain": FRAME if chain is None else chain, "window": window},
        **extra,
    }


def test_combo_is_saved_before_next_click_even_without_focus_event() -> None:
    it = Interpreter()
    it.feed(
        ev(
            "active_descendant",
            1.0,
            "combo box",
            "Reason",
            "0/2",
            new={"role": "label", "name": "Return"},
        )
    )
    it.feed(ev("mouse_clicked", 1.2, "push button", "Choose", "0/3"))
    it.finish(2.0)
    actions = it.take()
    assert [a.type for a in actions] == ["select", "click"]
    assert actions[0].t == 1.0
    assert actions[0].value == "Return"


def test_detached_cell_editor_retains_table_window_and_column() -> None:
    it = Interpreter()
    it.feed(
        ev(
            "active_descendant",
            1.0,
            "table",
            "Lines",
            "0/2",
            window=9,
            new={"role": "label", "name": "185", "index": 6},
        )
    )
    it.feed(ev("focus", 1.1, "text", "", "0", window=0, chain=[], text="185"))
    it.feed(ev("text_changed", 1.2, "text", "", "0", window=0, chain=[], text="120"))
    it.finish(1.3)
    action = it.take()[0]
    assert action.type == "fill"
    assert action.seen.window == 9
    assert action.cell_index == 6
    assert action.value == "120"
    assert action.seen.node.name == "Lines"


def test_cell_editor_keeps_its_original_cell_after_selection_moves(tmp_path) -> None:
    from types import SimpleNamespace

    from maptelo.capture.java import JavaRecorder, JavaRecorderOptions
    from maptelo.desktop.jab import Table

    it = Interpreter()
    it.feed(
        ev(
            "active_descendant",
            1.0,
            "table",
            "Lines",
            "0/2",
            new={"role": "label", "name": "24,62", "index": 5},
        )
    )
    it.feed(ev("focus", 1.1, "text", "", "0", window=0, chain=[], text="30"))
    it.feed(ev("text_changed", 1.2, "text", "", "0", window=0, chain=[], text="24,62"))
    it.feed(
        ev(
            "active_descendant",
            1.3,
            "table",
            "Other",
            "0/3",
            new={"role": "label", "name": "9", "index": 0},
        )
    )
    it.feed(ev("focus", 1.4, "table", "Other", "0/3"))
    [act] = it.take()
    assert act.seen.node.path == "0/2"
    assert act.cell_index == 5
    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    rec.bridge = SimpleNamespace(
        table=lambda hwnd, path: Table(
            headers=["SKU", "Price"],
            rows=[["A", "10"], ["B", "20"], ["C", "24,62"]],
            selected=[],
        )
    )
    rec._row_of(act)
    assert act.row.table == "Lines"
    assert act.row.index == 2
    assert act.row.cells == {"SKU": "C", "Price": "24,62"}
    assert act.column == "Price"


def test_ordinary_field_does_not_inherit_last_table_cell() -> None:
    it = Interpreter()
    it.feed(
        ev(
            "active_descendant",
            1.0,
            "table",
            "Lines",
            "0/2",
            new={"role": "label", "name": "24,62", "index": 5},
        )
    )
    typed(it, 1.1, "Reason", "0/3", "Return")
    it.finish(3)
    [act] = it.take()
    assert act.cell_index is None
    assert act.seen.node.name == "Reason"


def test_detached_checkbox_change_is_one_table_action() -> None:
    it = Interpreter()
    it.feed(
        ev(
            "active_descendant",
            1.0,
            "table",
            "WZ",
            "0/2",
            new={"role": "check box", "name": "", "index": 0},
        )
    )
    it.feed(
        ev(
            "state_changed",
            1.1,
            "check box",
            "",
            "0",
            window=0,
            chain=[],
            old="(null)",
            new="checked",
        )
    )
    it.feed(ev("mouse_clicked", 1.2, "table", "WZ", "0/2"))
    actions = it.take()
    assert len(actions) == 1
    assert actions[0].type == "check"
    assert actions[0].cell_index == 0


def test_private_capture_never_reads_pixels(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from maptelo.capture.java import JavaRecorder, JavaRecorderOptions
    from maptelo.desktop.screen import build_screen

    rec = JavaRecorder(tmp_path, JavaRecorderOptions(private=True))
    rec.bridge = SimpleNamespace(clock=lambda: 1.0)
    written = []
    rec.writer = SimpleNamespace(write=written.append)
    monkeypatch.setattr(rec, "_screen", lambda hwnd: build_screen("Test", hwnd, []))
    monkeypatch.setattr(rec, "_drain", lambda: None)
    monkeypatch.setattr(
        "maptelo.capture.java._screenshot",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("private recording must not capture pixels")
        ),
    )
    rec._capture(1, 1.0)
    assert written[0].screenshot is None


def test_next_press_keeps_the_previous_result_in_its_window_before_new_dialog(
    tmp_path, monkeypatch
):
    """Przelicz opens an error before its click is delivered; the preceding checkbox's
    result must still show the main form's PO, not the new error dialog."""
    from types import SimpleNamespace

    from maptelo.capture.java import Act, JavaRecorder, JavaRecorderOptions
    from maptelo.desktop.jab import Window

    main, error = Window(1, "SRK", 7, True), Window(9, "Error", 7, True, owner=1)
    pressed = ev("mouse_pressed", 2.0, "push button", "Recalculate", "0/2", window=1)
    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    rec.main = main
    rec.bridge = SimpleNamespace(clock=lambda: 2.01, events=lambda: [pressed])
    rec._windows = {1: main, 9: error}
    rec._pending = [(Act("check", 1.0, None), "before-checkbox")]
    captures, writes = [], []
    monkeypatch.setattr(rec, "_app_windows", lambda: [main, error])
    monkeypatch.setattr(rec, "_window_of", lambda source: source["window"])
    monkeypatch.setattr(rec, "_refresh_windows", lambda: None)
    monkeypatch.setattr(rec, "_front_window", lambda since=None: 9)
    monkeypatch.setattr(
        rec, "_capture", lambda hwnd, until: captures.append((hwnd, until)) or "after-checkbox"
    )
    monkeypatch.setattr(
        rec, "_write_act", lambda act, before, after: writes.append((act.type, before, after))
    )
    assert rec.pump() == 1
    assert captures == [(1, 2.0)]
    assert writes == [("check", "before-checkbox", "after-checkbox")]


def test_an_act_told_after_the_message_it_brought_up_is_on_its_own_window(tmp_path, monkeypatch):
    """The bridge told the click on „Przelicz” only after the error it brought up had been read
    as the last screen (benchmark D03 r6): a person cannot click a window under a message, so
    the click's screen before it is its own window, read again as it was just before."""
    from types import SimpleNamespace

    from maptelo.capture.java import Act, JavaRecorder, JavaRecorderOptions
    from maptelo.desktop.jab import Window

    main, error = Window(1, "SRK", 7, True), Window(9, "Error", 7, True, owner=1)
    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    rec._windows = {1: main, 9: error}
    rec._depth = {1: 0, 9: 1}
    rec._state_screens = {"s005": SimpleNamespace(hwnd=9), "s004": SimpleNamespace(hwnd=1)}
    captures = []
    monkeypatch.setattr(
        rec, "_capture", lambda hwnd, until: captures.append((hwnd, until)) or "s006"
    )
    click = Act("click", 3.8, SimpleNamespace(window=1))  # type: ignore[arg-type]
    rec._last_state = "s005"  # the error window, read before the click was told
    assert rec._before(click) == "s006"
    assert captures == [(1, 3.8 - rec.interpreter.press_s)]
    answer = Act("click", 4.5, SimpleNamespace(window=9))  # type: ignore[arg-type]
    assert rec._before(answer) == "s005"  # OK in the error window: the error is its screen
    rec._last_state = "s004"
    assert rec._before(click) == "s004"  # the main window read last: nothing to read again
    assert len(captures) == 1


def test_a_menu_command_keeps_the_screen_it_was_chosen_on(tmp_path, monkeypatch):
    """File > Save is chosen in the menu's own window, which has no title (benchmark D06): the
    command's screen is the one it was chosen on, not the main window read again (that made the
    Navigator the screen of „Save”, and 0 of 15 rows were done)."""
    from types import SimpleNamespace

    from maptelo.capture.java import Act, JavaRecorder, JavaRecorderOptions
    from maptelo.desktop.jab import Window

    main, menu = Window(1, "Oracle Applications", 7, True), Window(5, "", 7, True, owner=1)
    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    rec._windows = {1: main, 5: menu}
    rec._depth = {1: 0, 5: 1}
    rec._state_screens = {"s010": SimpleNamespace(hwnd=5)}
    rec._last_state = "s010"
    captures = []
    monkeypatch.setattr(rec, "_capture", lambda hwnd, until: captures.append(hwnd) or "s011")
    save = Act("click", 5.0, SimpleNamespace(window=1), menu="File")  # type: ignore[arg-type]
    assert rec._before(save) == "s010"
    click = Act("click", 5.2, SimpleNamespace(window=1))  # type: ignore[arg-type]
    assert rec._before(click) == "s010"  # no message over the window: nothing to read again
    assert captures == []


def test_new_dialog_without_a_next_human_action_remains_the_result(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from maptelo.capture.java import Act, JavaRecorder, JavaRecorderOptions
    from maptelo.desktop.jab import Window

    main, error = Window(1, "SRK", 7, True), Window(9, "Error", 7, True, owner=1)
    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    rec.main = main
    rec.bridge = SimpleNamespace(clock=lambda: 3.0, events=list)
    rec._windows = {1: main, 9: error}
    rec._pending = [(Act("click", 1.0, None), "before")]
    captures = []
    monkeypatch.setattr(rec, "_app_windows", lambda: [main, error])
    monkeypatch.setattr(rec, "_refresh_windows", lambda: None)
    monkeypatch.setattr(rec, "_front_window", lambda since=None: 9)
    monkeypatch.setattr(rec, "_capture", lambda hwnd, until: captures.append(hwnd) or "dialog")
    monkeypatch.setattr(rec, "_write_act", lambda *args: None)
    assert rec.pump() == 1
    assert captures == [9]


def typed(it: Interpreter, t: float, name: str, path: str, value: str) -> None:
    it.feed(ev("mouse_clicked", t, "text", name, path, text=value))
    it.feed(ev("focus", t + 0.01, "text", name, path, text=value))
    for i in range(1, len(value) + 1):
        it.feed(ev("text_changed", t + 0.02 * i, "text", name, path, text=value[:i]))


def test_typing_then_the_screen_reacting_is_a_fill_and_enter() -> None:
    it = Interpreter()
    typed(it, 1.0, "Kontrahent", "0/1/0", "K0010")
    it.feed({"kind": "visible_data_changed", "t": 1.3, "source": {"node": {"role": "table"}}})
    it.tick(1.4)
    assert it.acts == []  # the reaction may go on: not yet
    it.tick(1.7)
    acts = it.take()
    assert [(a.type, a.value) for a in acts] == [("fill", "K0010"), ("press", "Enter")]
    assert acts[1].seen is not None
    assert acts[1].seen.node.name == "Kontrahent"


def test_what_the_program_redraws_as_a_field_is_typed_is_no_enter() -> None:
    """SRK recounts the invoice as the PO is typed: a burst of label updates from the last
    keystroke on is the typing's echo; the person then clicks Przelicz (benchmark D03)."""
    it = Interpreter()
    typed(it, 1.0, "Numer zamówienia klienta (PO)", "0/1/4", "PO-79487")
    last = 1.0 + 0.02 * len("PO-79487")
    for i in range(1, 40):  # every 4 ms, from 1 ms after the last keystroke
        label = {"node": {"role": "label", "name": "Brutto"}, "window": 1}
        it.feed({"kind": "visible_data_changed", "t": last + 0.001 + 0.004 * i, "source": label})
    later = {"node": {"role": "label", "name": "Brutto"}, "window": 1}  # told after a pause
    it.feed({"kind": "visible_data_changed", "t": last + 0.3, "source": later})
    it.tick(last + 0.4)
    it.feed(ev("mouse_pressed", last + 0.5, "push button", "Przelicz", "0/1/9"))
    it.feed(ev("mouse_clicked", last + 0.51, "push button", "Przelicz", "0/1/9"))
    assert [(a.type, a.value) for a in it.take()] == [("fill", "PO-79487"), ("click", None)]


def test_labels_redrawn_after_typing_are_no_enter() -> None:
    """The totals redrawn as the PO is typed, told 70 ms after the last keystroke and again
    later (benchmark D03): no Enter."""
    it = Interpreter()
    typed(it, 1.0, "Numer zamówienia klienta (PO)", "0/1/4", "PO-79487")
    last = 1.0 + 0.02 * len("PO-79487")
    for delay in (0.07, 0.15, 0.3):
        label = {"node": {"role": "label", "name": "Brutto"}, "window": 0}
        it.feed({"kind": "visible_data_changed", "t": last + delay, "source": label})
    it.tick(last + 0.7)
    it.feed(ev("mouse_pressed", last + 0.8, "push button", "Przelicz", "0/1/9"))
    it.feed(ev("mouse_clicked", last + 0.81, "push button", "Przelicz", "0/1/9"))
    assert [(a.type, a.value) for a in it.take()] == [("fill", "PO-79487"), ("click", None)]


def test_something_else_changing_after_the_echo_is_enter() -> None:
    it = Interpreter()
    typed(it, 1.0, "Indeks", "0/1/4", "26386-F")
    last = 1.0 + 0.02 * len("26386-F")
    echo = {"node": {"role": "label", "name": "Indeks - opis"}, "window": 1}
    it.feed({"kind": "visible_data_changed", "t": last + 0.001, "source": echo})
    table = {"node": {"role": "table", "name": "Ceny"}, "window": 1}
    it.feed({"kind": "visible_data_changed", "t": last + 0.4, "source": table})
    it.tick(last + 0.8)
    assert [(a.type, a.value) for a in it.take()] == [("fill", "26386-F"), ("press", "Enter")]


def test_enter_is_told_by_the_order_however_quickly_the_person_goes_on() -> None:
    """Benchmark: the price list loaded and the next button was clicked before the quiet the
    recorder waits for."""
    it = Interpreter()
    typed(it, 1.0, "Kontrahent", "0/1/0", "K0010")
    it.feed({"kind": "visible_data_changed", "t": 1.12, "source": {"node": {"role": "table"}}})
    it.feed({"kind": "visible_data_changed", "t": 1.2, "source": {"node": {"role": "label"}}})
    it.feed(ev("mouse_pressed", 1.3, "push button", "Nowa wersja ceny", "0/1/1"))
    it.feed(ev("mouse_clicked", 1.31, "push button", "Nowa wersja ceny", "0/1/1"))
    acts = it.take()
    assert [(a.type, a.value) for a in acts] == [
        ("fill", "K0010"),
        ("press", "Enter"),
        ("click", None),
    ]


def test_what_the_press_itself_does_is_not_enter() -> None:
    """Benchmark: a list's popup opening (or a button armed) is said a moment before the press
    that opened it."""
    it = Interpreter()
    typed(it, 1.0, "Obowiązuje od", "0/1/0", "2026-11-01")
    it.feed({"kind": "child_changed", "t": 2.995, "source": {"node": {"role": "popup menu"}}})
    it.feed(ev("mouse_pressed", 3.0, "combo box", "Powód zmiany", "0/1/2"))
    it.feed(ev("mouse_clicked", 3.01, "combo box", "Powód zmiany", "0/1/2"))
    it.tick(3.5)
    it.finish(3.6)
    acts = it.take()
    assert [(a.type, a.value) for a in acts] == [("fill", "2026-11-01")]


def test_a_check_when_the_field_loses_the_focus_is_not_enter() -> None:
    """Clicking elsewhere takes the focus from the field first; what the program does then (a
    description filled in) comes after the press."""
    it = Interpreter()
    typed(it, 1.0, "Indeks", "0/1/0", "26386-F")
    it.feed(ev("mouse_pressed", 2.0, "push button", "Zapisz", "0/1/1"))
    it.feed({"kind": "visible_data_changed", "t": 2.01, "source": {"node": {"role": "label"}}})
    it.feed(ev("focus", 2.02, "push button", "Zapisz", "0/1/1"))
    it.feed(ev("mouse_clicked", 2.03, "push button", "Zapisz", "0/1/1"))
    it.tick(2.5)
    acts = it.take()
    assert [(a.type, a.value) for a in acts] == [("fill", "26386-F"), ("click", None)]


def test_what_a_button_does_before_its_click_is_told_is_not_enter() -> None:
    """A name typed into Szukaj, then Znajdź pressed: the list of people filled, told 1 ms
    after the press and before the click (the bridge was busy), is the button's doing: no
    Enter (benchmark D04)."""
    it = Interpreter()
    typed(it, 1.0, "Szukaj", "0/1/2", "Katarzyna Lewandowska")
    last = 1.0 + 0.02 * len("Katarzyna Lewandowska")
    it.tick(last + 0.3)
    it.feed(ev("mouse_pressed", last + 0.6, "push button", "Znajdź", "0/1/3"))
    table = {"node": {"role": "table", "name": "Osoby"}, "window": 1}
    it.feed({"kind": "visible_data_changed", "t": last + 0.601, "source": table})
    it.tick(last + 0.65)
    it.feed(ev("mouse_clicked", last + 0.7, "push button", "Znajdź", "0/1/3"))
    it.tick(last + 1.5)
    acts = it.take()
    assert [(a.type, a.value) for a in acts] == [
        ("fill", "Katarzyna Lewandowska"),
        ("click", None),
    ]


def test_a_reaction_before_the_press_is_still_enter() -> None:
    """What the program did before the person reached for the mouse answered the typing."""
    it = Interpreter()
    typed(it, 1.0, "Kontrahent", "0/1/0", "K0010")
    table = {"node": {"role": "table", "name": "Ceny"}, "window": 1}
    it.feed({"kind": "visible_data_changed", "t": 1.15, "source": table})
    it.feed(ev("mouse_pressed", 1.3, "push button", "Nowa wersja ceny", "0/1/1"))
    it.feed({"kind": "visible_data_changed", "t": 1.31, "source": table})
    it.feed(ev("mouse_clicked", 1.4, "push button", "Nowa wersja ceny", "0/1/1"))
    acts = it.take()
    assert [(a.type, a.value) for a in acts] == [
        ("fill", "K0010"),
        ("press", "Enter"),
        ("click", None),
    ]


def test_typing_again_after_a_click_in_the_same_field_can_be_entered() -> None:
    """A click back into the field the person types into is not going on: what the program
    does after more typing answers it."""
    it = Interpreter()
    typed(it, 1.0, "Kontrahent", "0/1/0", "K00")
    it.feed(ev("mouse_pressed", 1.2, "text", "Kontrahent", "0/1/0", text="K00"))
    it.feed(ev("mouse_clicked", 1.21, "text", "Kontrahent", "0/1/0", text="K00"))
    it.feed(ev("text_changed", 1.3, "text", "Kontrahent", "0/1/0", text="K001"))
    it.feed(ev("text_changed", 1.32, "text", "Kontrahent", "0/1/0", text="K0010"))
    table = {"node": {"role": "table", "name": "Ceny"}, "window": 1}
    it.feed({"kind": "visible_data_changed", "t": 1.5, "source": table})
    it.tick(2.0)
    assert [(a.type, a.value) for a in it.take()] == [("fill", "K0010"), ("press", "Enter")]


def test_typing_then_clicking_a_button_is_a_fill_and_a_click() -> None:
    it = Interpreter()
    typed(it, 1.0, "Nowa cena netto", "0/0/9", "6,04")
    it.feed(ev("mouse_clicked", 2.0, "push button", "Zapisz", "0/1/0", chain=DIALOG))
    acts = it.take()
    assert [(a.type, a.value) for a in acts] == [("fill", "6,04"), ("click", None)]
    assert acts[1].seen is not None
    assert acts[1].seen.frame == "Nowa wersja ceny – K0010"


def test_a_value_already_there_is_not_typed() -> None:
    it = Interpreter()
    it.remember(1, {"0/0/9": "6,04"}, 0.5)
    typed(it, 1.0, "Nowa cena netto", "0/0/9", "6,04")
    it.feed(ev("mouse_clicked", 2.0, "push button", "Zapisz", "0/1/0"))
    assert [a.type for a in it.take()] == ["click"]


def test_a_screen_read_while_typing_does_not_say_what_was_there_before() -> None:
    it = Interpreter()
    it.remember(1, {"0/0/9": "6,04"}, 1.5)  # read after the field got the focus
    typed(it, 1.0, "Nowa cena netto", "0/0/9", "6,04")
    it.feed(ev("mouse_clicked", 2.0, "push button", "Zapisz", "0/1/0"))
    assert [a.type for a in it.take()] == ["fill", "click"]


def test_a_combo_box_choice_is_a_select() -> None:
    it = Interpreter()
    it.feed(ev("mouse_clicked", 1.0, "combo box", "Powód zmiany", "0/0/17"))
    it.feed(ev("focus", 1.01, "combo box", "Powód zmiany", "0/0/17"))
    it.feed(
        ev(
            "active_descendant",
            1.2,
            "combo box",
            "Powód zmiany",
            "0/0/17",
            new={"role": "label", "name": "Negocjacje handlowe"},
        )
    )
    typed(it, 2.0, "Podstawa", "0/0/19", "Plik")
    it.feed(ev("mouse_clicked", 3.0, "push button", "Zapisz", "0/1/0"))
    acts = it.take()
    assert [(a.type, a.value) for a in acts] == [
        ("select", "Negocjacje handlowe"),
        ("fill", "Plik"),
        ("click", None),
    ]


def test_a_menu_item_is_clicked_in_its_menu() -> None:
    it = Interpreter()
    it.feed(ev("menu_selected", 1.0, "menu", "Ceny", "0/0/1/1/2"))
    it.feed(ev("mouse_pressed", 1.1, "menu item", "Cennik klienta", "0/0/1/1/2/0"))
    it.feed(ev("mouse_clicked", 1.15, "menu item", "Cennik klienta", "0/0/1/1/2/0"))
    acts = it.take()
    assert [(a.type, a.menu) for a in acts] == [("click", "Ceny")]


def test_a_box_ticked_is_a_check() -> None:
    it = Interpreter()
    it.feed(ev("mouse_clicked", 1.0, "check box", "Faktura zbiorcza", "0/0/5"))
    it.feed(
        ev("state_changed", 1.01, "check box", "Faktura zbiorcza", "0/0/5", old="", new="checked")
    )
    assert [a.type for a in it.take()] == ["check"]


def test_the_answer_to_a_question_keeps_the_question() -> None:
    """The button that closes a question is described after it closed: no window, no dialog
    around it. What was seen of it a moment before says where it was."""
    it = Interpreter()
    question = [("option pane", ""), ("dialog", "SRK – pytanie")]
    it.feed(ev("focus", 1.0, "push button", "Tak", "0/0/1/0", window=7, chain=question))
    it.feed(
        ev(
            "mouse_clicked",
            2.0,
            "push button",
            "Tak",
            "0/1/0",
            window=0,
            chain=[("option pane", "")],
        )
    )
    acts = it.take()
    assert len(acts) == 1
    assert acts[0].seen is not None
    assert acts[0].seen.window == 7
    assert acts[0].seen.frame == "SRK – pytanie"


def test_titles_and_names() -> None:
    assert title_template("Nowa wersja ceny – K0010") == "Nowa wersja ceny – *"
    assert title_template("Cennik klienta") == "Cennik klienta"
    assert program_name("SRK 4.2.7 – System Rozliczeń z Klientami [PROD] – Anna Nowak") == "srk"
    assert display_name("SRK 4.2.7 – System Rozliczeń z Klientami [PROD] – Anna Nowak") == "SRK"
    assert display_name("Oracle Applications - TEST") == "Oracle Applications"
    assert screen_url("srk", "Nowa wersja ceny – K0010") == "java://srk/Nowa wersja ceny – *"
    assert screen_url("srk", None) == "java://srk/"


def test_a_click_in_a_table_keeps_the_cell_the_table_chose() -> None:
    it = Interpreter()
    table = ev("active_descendant", 3.0, "table", "", "0/2", new={"name": "FV/2026/0042"})
    it.feed(table)
    it.feed(ev("mouse_clicked", 3.01, "table", "", "0/2"))
    [act] = it.take()
    assert (act.type, act.cell) == ("click", "FV/2026/0042")


def test_the_program_writing_a_field_again_after_enter_is_its_reaction() -> None:
    """Benchmark D05: Enter in the customer's field, and SRK writes the code back into it (the
    bridge says the text changed, twice, to what it was): Enter, not more typing."""
    it = Interpreter()
    typed(it, 1.0, "Kontrahent", "0/1/0", "K0012")
    it.feed(ev("text_changed", 1.75, "text", "Kontrahent", "0/1/0", text="K0012"))
    it.feed(ev("text_changed", 1.76, "text", "Kontrahent", "0/1/0", text="K0012"))
    it.feed(ev("mouse_pressed", 2.7, "push button", "Wybierz: Faktura", "0/1/1"))
    it.feed(ev("mouse_clicked", 2.71, "push button", "Wybierz: Faktura", "0/1/1"))
    acts = it.take()
    assert [(a.type, a.value) for a in acts] == [
        ("fill", "K0012"),
        ("press", "Enter"),
        ("click", None),
    ]


def test_a_button_whose_click_never_comes_was_clicked() -> None:
    """Benchmark D06: Find in the Find window gives way to the form before the release is told."""
    it = Interpreter()
    find = [("internal frame", "Find Price Lists"), ("frame", "Wiorek Applications - WRK1")]
    typed(it, 1.0, "Name List of Values", "0/0/1", "WRK-K0010-2026")
    it.feed(ev("mouse_pressed", 2.0, "push button", "Find ALT I", "0/0/2", chain=find))
    it.tick(2.2)
    assert it.acts == []  # the click may still come
    it.feed(ev("mouse_pressed", 3.5, "text", "End Date", "0/1/9"))  # the next act
    acts = it.take()
    assert [(a.type, a.seen.node.name if a.seen else None) for a in acts] == [
        ("fill", "Name List of Values"),
        ("click", "Find ALT I"),
    ]


def test_a_button_clicked_is_one_click() -> None:
    it = Interpreter()
    it.feed(ev("mouse_pressed", 1.0, "push button", "Zapisz", "0/1"))
    it.feed(ev("mouse_clicked", 1.05, "push button", "Zapisz", "0/1"))
    it.tick(2.0)
    assert [a.type for a in it.take()] == ["click"]


def test_an_act_whose_next_came_in_the_same_batch_gets_the_screen_at_its_start() -> None:
    """The WZ's row clicked, then Przelicz pressed and clicked within one batch of events: the
    row's screen is the one when Przelicz was pressed (with the PO the row brought), not the
    screen after the next act (benchmark D03)."""
    from maptelo.capture.java import Act, JavaRecorder, Seen
    from maptelo.desktop.jab import Node

    def seen(role: str, name: str) -> Seen:
        node = Node(
            path="0/1", role=role, name=name, states=frozenset({"showing"}), box=(0, 0, 9, 9)
        )
        return Seen(node, [], 7)

    row = Act("click", 4.275, seen("table", "Dokumenty WZ"))
    przelicz = Act("click", 4.703, seen("push button", "Przelicz"))
    rec = JavaRecorder.__new__(JavaRecorder)
    rec._pending = [(row, "s003"), (przelicz, "s003")]
    rec._human = [4.033, 4.125, 4.275, 4.69, 4.703]
    rec._windows = {7: None}  # type: ignore[dict-item]
    rec._captured_at = 3.39
    rec._last_state = "s003"
    read: list[tuple[int, float]] = []
    written: list[tuple[float, str | None, str | None]] = []
    rec._refresh_windows = lambda: None  # type: ignore[method-assign]
    rec._capture = lambda hwnd, until: read.append((hwnd, until)) or "s004"  # type: ignore[method-assign]
    rec._write_act = lambda act, before, after: written.append((act.t, before, after))  # type: ignore[method-assign]
    assert rec._settle_earlier() == 1
    assert read == [(7, 4.69)]  # the window Przelicz is in, as it was when it was pressed
    assert written == [(4.275, "s003", "s004")]
    assert rec._pending == [(przelicz, "s004")]  # Przelicz waits for its own screen


def test_the_status_line_answering_after_typing_is_enter() -> None:
    """SRK answers an invoice number it does not know only in its status line ("Faktura: brak
    pozycji"): that is the program's answer to an Enter, not an echo of the typing (benchmark
    D04). Another label redrawn the same way stays an echo."""
    it = Interpreter()
    it.status_labels.add(("label", "Pasek stanu"))
    typed(it, 1.0, "Faktura", "0/1/4", "FV/2026/08/0005")
    last = 1.0 + 0.02 * len("FV/2026/08/0005")
    status = {"node": {"role": "label", "name": "Pasek stanu"}, "window": 0}
    it.feed({"kind": "visible_data_changed", "t": last + 0.05, "source": status})
    it.tick(last + 0.6)
    assert [(a.type, a.value) for a in it.take()] == [
        ("fill", "FV/2026/08/0005"),
        ("press", "Enter"),
    ]
    other = Interpreter()
    other.status_labels.add(("label", "Pasek stanu"))
    typed(other, 1.0, "Faktura", "0/1/4", "FV/2026/08/0005")
    total = {"node": {"role": "label", "name": "Różnica brutto"}, "window": 0}
    other.feed({"kind": "visible_data_changed", "t": last + 0.05, "source": total})
    other.tick(last + 0.6)
    other.feed(ev("mouse_pressed", last + 0.8, "push button", "Przelicz", "0/1/9"))
    other.feed(ev("mouse_clicked", last + 0.81, "push button", "Przelicz", "0/1/9"))
    assert [(a.type, a.value) for a in other.take()] == [
        ("fill", "FV/2026/08/0005"),
        ("click", None),
    ]


def test_a_window_opened_by_a_click_the_bridge_tells_late_is_no_enter() -> None:
    """The basis typed, then "SRK - pytanie" seen open before the bridge (busy reading the new
    window) told the click on Zapisz that opened it: no Enter in the basis (benchmark D04)."""
    it = Interpreter()
    typed(it, 1.0, "Podstawa akceptacji", "0/1/7", "mail z 06.10")
    last = 1.0 + 0.02 * len("mail z 06.10")
    it.feed({"kind": "windows_changed", "t": last + 0.09})
    it.tick(last + 0.5)  # a reaction for longer than an Enter's
    assert it.acts == []
    it.feed(ev("mouse_pressed", last + 0.16, "push button", "Zapisz", "0/1/9"))
    it.feed(ev("mouse_clicked", last + 0.17, "push button", "Zapisz", "0/1/9"))
    it.tick(last + 1.5)
    assert [(a.type, a.value) for a in it.take()] == [("fill", "mail z 06.10"), ("click", None)]


def test_a_window_seen_well_before_a_late_press_in_the_typed_window_is_no_enter() -> None:
    """The basis typed, "SRK - pytanie" seen open 107 ms before the bridge told the press on
    Zapisz in the window being typed into (benchmark D04, round r2): the press opened it."""
    it = Interpreter()
    typed(it, 1.0, "Podstawa akceptacji", "0/1/7", "mail z 06.10")
    last = 1.0 + 0.02 * len("mail z 06.10")
    it.feed({"kind": "windows_changed", "t": last + 0.47})
    it.tick(last + 0.55)
    it.feed(ev("mouse_pressed", last + 0.58, "push button", "Zapisz", "0/1/9"))
    it.feed(ev("mouse_clicked", last + 0.60, "push button", "Zapisz", "0/1/9"))
    it.tick(last + 2.0)
    assert [(a.type, a.value) for a in it.take()] == [("fill", "mail z 06.10"), ("click", None)]


def test_a_click_in_the_window_the_typing_opened_keeps_the_enter() -> None:
    """Enter in the invoice's field opened its list of values; the person picks a row in it at
    once: the window answered the typing."""
    it = Interpreter()
    typed(it, 1.0, "Faktura", "0/1/4", "FV/2026/08")
    last = 1.0 + 0.02 * len("FV/2026/08")
    it.feed({"kind": "windows_changed", "t": last + 0.2})
    chain = [("dialog", "Wybór faktury"), ("frame", "SRK 4.2.7")]
    it.feed(ev("mouse_pressed", last + 0.6, "table", "Faktury", "0/0/2", window=2, chain=chain))
    it.feed(ev("mouse_clicked", last + 0.62, "table", "Faktury", "0/0/2", window=2, chain=chain))
    acts = it.take()
    assert [(a.type, a.value) for a in acts][:2] == [("fill", "FV/2026/08"), ("press", "Enter")]


def test_a_window_the_typing_opened_is_an_enter() -> None:
    """Enter in a code field opens the list of values when the code is not exact: the window
    is its answer when no click comes."""
    it = Interpreter()
    typed(it, 1.0, "Faktura", "0/1/4", "FV/2026/08")
    last = 1.0 + 0.02 * len("FV/2026/08")
    it.feed({"kind": "windows_changed", "t": last + 0.2})
    it.tick(last + 0.7)
    assert it.acts == []  # a click may still come
    it.tick(last + 1.3)
    assert [(a.type, a.value) for a in it.take()] == [("fill", "FV/2026/08"), ("press", "Enter")]


def test_a_button_that_closed_its_window_keeps_its_place_from_the_screen_before() -> None:
    """„Tak” in a question: the bridge has no place for it once the question closed (it says
    -1), the screen read before the click has it; and nothing at all is no place."""
    from maptelo.capture.java import Seen, element_info
    from maptelo.desktop.jab import Node
    from maptelo.desktop.screen import build_screen

    shown = frozenset({"enabled", "showing", "visible"})
    gone = Node("0/1", "push button", "Tak", box=(-1, -1, -1, -1))
    seen = Seen(gone, [("dialog", "SRK pytanie")], 2)
    before = build_screen(
        "SRK pytanie",
        2,
        [
            Node("0", "dialog", "SRK pytanie", states=shown, box=(1090, 575, 382, 232)),
            Node("0/1", "push button", "Tak", states=shown, box=(1230, 760, 50, 24)),
        ],
    )
    assert element_info(seen, before).bbox == (1230, 760, 50, 24)
    assert element_info(seen, None).bbox is None
    here = Node("0/1", "push button", "Tak", box=(1231, 761, 50, 24))
    assert element_info(Seen(here, seen.chain, 2), before).bbox == (1231, 761, 50, 24)
