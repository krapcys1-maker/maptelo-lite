# ruff: noqa: RUF001
"""What a person did in a Java program, told from the Access Bridge's events (keys are not
among them: Enter is told by the screen reacting while the field keeps the focus)."""

from __future__ import annotations

from typing import Any

from maptelo.capture.java import (
    Echoes,
    Interpreter,
    display_name,
    program_name,
    screen_url,
    title_template,
)

FRAME = [("internal frame", "Cennik klienta"), ("frame", "SRK 4.2.7")]
DIALOG = [("dialog", "Nowa wersja ceny – K0010"), ("frame", "SRK 4.2.7")]


def test_reopened_lookup_keeps_its_own_window_and_table(tmp_path) -> None:
    from maptelo.capture.java import JavaRecorder, JavaRecorderOptions
    from maptelo.desktop.jab import Window

    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    old = Window(90, "Products", 7, True, owner=1)
    current = Window(20, "Products", 7, True, owner=1)
    rec._ever = {90: old, 20: current}
    rec._windows = {20: current}
    source = {"window": 20, "chain": [("dialog", "Products"), ("frame", "ERP")]}
    assert rec._window_of(source) == 20
    assert rec._window_of(dict(source, window=1)) == 20
    rec._windows = {}  # the second lookup closed before its click was described
    assert rec._window_of(source) == 20
    assert rec._window_of(dict(source, window=1)) == 20


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


def test_a_row_of_a_list_of_values_clicked_is_a_step() -> None:
    """EBS „Items” (a list of values over the price list): the bridge tells the click on the
    list itself and its row as the list's active descendant. The click was lost, so the map
    typed „26386%” and clicked an OK no row had enabled; it is the click on that row."""
    items = [("internal frame", "Items"), ("frame", "Wiorek Applications - WRK1")]
    row = "Item Number:26386-F\tDescription:Pudło fasonowe 200x150x100 białe\tUOM:Ea"
    lov = "0/0/1/0/1/0/0/1/0/1/0/0"
    it = Interpreter()
    it.feed(ev("active_descendant", 4.02, "list", "", lov, chain=items,
               new={"role": "label", "name": row, "index": 0}))  # fmt: skip
    it.feed(ev("mouse_pressed", 4.064, "list", "", lov, chain=items))
    it.feed(ev("mouse_clicked", 4.083, "list", "", lov, chain=items))
    it.feed(ev("mouse_pressed", 4.833, "push button", "OK ALT O", "0/0/1/0/2/1", chain=items[:1]))
    it.feed(ev("mouse_clicked", 4.84, "push button", "OK ALT O", "0/0/1/0/2/1", chain=items[:1]))
    it.finish(6.0)
    acts = it.take()
    assert [(a.type, a.seen.node.role, a.seen.node.name) for a in acts if a.seen] == [
        ("click", "label", row),
        ("click", "push button", "OK ALT O"),
    ]
    chosen = acts[0].seen
    assert chosen is not None
    assert (chosen.node.path, chosen.frame) == (lov + "/0", "Items")
    nothing = Interpreter()  # a click on a list with no row told: no step
    nothing.feed(ev("mouse_clicked", 1.0, "list", "", lov, chain=items))
    nothing.finish(2.0)
    assert nothing.take() == []
    # a combo box's own popup list (SRK „Powód zmiany”, the list under the box): its choice
    # is the step, the click on the list is not another one
    box, popup = "0/0/1/0/0/17", "0/0/1/0/0/17/0/0/0/0"
    combo = Interpreter()
    combo.feed(ev("mouse_clicked", 1.0, "combo box", "Powód zmiany", box))
    combo.feed(ev("active_descendant", 1.1, "list", "", popup,
                  new={"role": "label", "name": "Negocjacje handlowe", "index": 0}))  # fmt: skip
    combo.feed(ev("active_descendant", 1.15, "combo box", "Powód zmiany", box,
                  new={"role": "label", "name": "Negocjacje handlowe"}))  # fmt: skip
    combo.feed(ev("mouse_pressed", 1.2, "list", "", popup))
    combo.feed(ev("mouse_clicked", 1.21, "list", "", popup))
    combo.finish(3.0)
    assert [(a.type, a.value) for a in combo.take()] == [("select", "Negocjacje handlowe")]


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


def test_a_picture_without_the_invisible_borders_starts_where_its_frame_does(tmp_path, monkeypatch):
    """The picture leaves out the window's invisible borders (``visible_inset``): marks on it
    are drawn from its visible frame's corner, not from the rectangle's."""
    from types import SimpleNamespace

    from maptelo.capture.java import JavaRecorder, JavaRecorderOptions
    from maptelo.desktop.jab import Node
    from maptelo.desktop.screen import build_screen

    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    rec.bridge = SimpleNamespace(clock=lambda: 1.0)
    written = []
    rec.writer = SimpleNamespace(write=written.append)
    shown = frozenset({"enabled", "showing", "visible"})
    question = [Node("0", "dialog", "SRK pytanie", states=shown, box=(1081, 575, 391, 241))]
    monkeypatch.setattr(rec, "_screen", lambda hwnd: build_screen("SRK pytanie", hwnd, question))
    monkeypatch.setattr(rec, "_drain", lambda: None)
    monkeypatch.setattr(
        "maptelo.capture.java._screenshot",
        lambda hwnd, path: (path, (1081, 575), (391, 241), (9, 0, 9, 9)),
    )
    rec._capture(2, 1.0)
    assert (written[0].origin, written[0].scale) == ((1090, 575), None)


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
    rec.bridge = SimpleNamespace(
        clock=lambda: 2.01, delivered=lambda: 2.01, events=lambda: [pressed]
    )
    rec._windows = {1: main, 9: error}
    rec._pending = [(Act("check", 1.0, None), "before-checkbox")]
    captures, writes = [], []
    monkeypatch.setattr(rec, "_app_windows", lambda: [main, error])
    monkeypatch.setattr(rec, "_window_of", lambda source, t=None: source["window"])
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


def test_a_menu_command_is_on_the_form_the_bridge_tells_open_though_a_busy_read_missed_it(
    tmp_path,
):
    """The screen read while the program was saving left the price list's form out, so Close
    Form, chosen on that form, became a step of the Navigator (benchmark D06: 11 rounds of 16,
    every record ending unclear and 15 s slower). The bridge told the form open until after
    the command: the command is on the form; a form closed before it is not."""
    from types import SimpleNamespace

    from maptelo.capture.java import Act, JavaRecorder, JavaRecorderOptions, Seen
    from maptelo.desktop.jab import Node, Window
    from maptelo.desktop.screen import build_screen

    shown = frozenset({"enabled", "showing", "visible"})
    main = Window(1, "Wiorek Applications - WRK1", 7, True)
    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    rec.app = "wiorek-applications"
    rec._windows = {1: main}
    written = []
    rec.writer = SimpleNamespace(write=written.append)
    busy = build_screen(  # only the Navigator: the price list's form left out
        main.title,
        1,
        [
            Node("0", "frame", main.title, states=shown, box=(0, 0, 1920, 1040)),
            Node(
                "0/1",
                "internal frame",
                "Navigator - Pricing Manager",
                states=shown,
                box=(20, 120, 440, 380),
            ),
            Node("0/1/0", "push button", "Open", states=shown, box=(30, 460, 70, 26)),
        ],
    )
    rec._state_screens = {"s009": busy}
    rec._screens = {1: busy}
    rec._worked_in = "Price Lists"  # its fields were typed into
    rec._note_frames([
        {"kind": "child_changed", "t": 2.5, "old": None,
         "new": {"role": "internal frame", "name": "Price Lists"}},
        {"kind": "child_changed", "t": 8.473, "new": None,
         "old": {"role": "internal frame", "name": "Price Lists"}},
    ])  # fmt: skip
    close = Node("0/0/1/1/0/4", "menu item", "Close Form")
    chosen = Seen(close, [("frame", main.title)], 1)
    rec._write_act(Act("click", 8.45, chosen, menu="File"), "s009", "s010")
    assert written[-1].url == "java://wiorek-applications/Price Lists"
    rec._write_act(Act("click", 9.2, chosen, menu="File"), "s009", "s011")  # closed by then
    assert written[-1].url == "java://wiorek-applications/Navigator - Pricing Manager"
    assert not rec._open_at("Price Lists", 1.0)  # not open yet
    assert not rec._open_at("Navigator - Pricing Manager", 5.0)  # never told: not known


def test_new_dialog_without_a_next_human_action_remains_the_result(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from maptelo.capture.java import Act, JavaRecorder, JavaRecorderOptions
    from maptelo.desktop.jab import Window

    main, error = Window(1, "SRK", 7, True), Window(9, "Error", 7, True, owner=1)
    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    rec.main = main
    rec.bridge = SimpleNamespace(clock=lambda: 3.0, delivered=lambda: 3.0, events=list)
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


def test_the_list_of_a_combo_box_told_early_is_no_enter() -> None:
    """A date typed, then the combo box below it clicked: its list opened and the bridge told
    it before the press, on a busy computer 85 ms before (benchmark D01 while another round
    ran: an Enter after the date, and the robot stopped on every row). The list is the press's
    own doing; an Enter whose answer came first still counts."""
    date, box = "0/0/1/0/0/12", "0/0/1/0/0/17"
    dialog = [("dialog", "Nowa wersja ceny – K0007"), ("frame", "SRK 4.2.7")]

    def opened(it: Interpreter, t: float) -> None:
        it.feed(ev("popup_visible", t, "combo box", "Powód zmiany", box, chain=dialog))
        it.feed({"kind": "child_changed", "t": t + 0.034, "source": {
            "node": {"path": "0/0/1", "role": "layered pane", "name": ""}, "chain": dialog,
            "window": 1}, "new": {"role": "panel", "name": ""}})  # fmt: skip
        it.feed(ev("mouse_pressed", t + 0.119, "combo box", "Powód zmiany", box, chain=dialog))
        it.feed(ev("mouse_clicked", t + 0.135, "combo box", "Powód zmiany", box, chain=dialog))

    busy = Interpreter()
    typed(busy, 1.0, "Obowiązuje od", date, "2026-11-01")
    opened(busy, 2.0)
    busy.finish(4.0)
    assert [(a.type, a.value) for a in busy.take()] == [("fill", "2026-11-01")]

    answered = Interpreter()  # the program answered the date before the list was opened
    typed(answered, 1.0, "Obowiązuje od", date, "2026-11-01")
    answered.feed({"kind": "visible_data_changed", "t": 1.6, "source": {"node": {"role": "table"}}})
    opened(answered, 2.0)
    answered.finish(4.0)
    assert [(a.type, a.value) for a in answered.take()] == [
        ("fill", "2026-11-01"),
        ("press", "Enter"),
    ]


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


def test_the_last_change_of_a_long_text_told_late_is_still_the_typing() -> None:
    """Benchmark M3: a file's path of 75 characters typed at once into Plik; the bridge tells
    its last change 0.45 s after the first, with the same text. Then Wczytaj, whose table comes
    with its press: no Enter in Plik (it made the typed path a way of its own)."""
    path = "C:/Zespol/Cenniki/" + "x" * 39 + "_cennik_K0018_2026-11.csv"
    it = Interpreter()
    it.feed(ev("focus", 0.9, "text", "Plik", "0/1", text=""))
    it.feed(ev("mouse_pressed", 1.252, "text", "Plik", "0/1", text=path))
    it.feed(ev("mouse_clicked", 1.265, "text", "Plik", "0/1", text=path))
    it.feed(ev("text_changed", 1.276, "text", "Plik", "0/1", text=path))
    it.feed(ev("text_changed", 1.723, "text", "Plik", "0/1", text=path))
    it.feed(ev("mouse_pressed", 2.23, "push button", "Wczytaj", "0/3"))
    it.feed(ev("visible_data_changed", 2.232, "table", "Wiersze pliku", "0/5"))
    it.feed(ev("mouse_clicked", 2.25, "push button", "Wczytaj", "0/3"))
    it.feed(ev("focus", 2.27, "push button", "Wczytaj", "0/3"))
    it.tick(4.0)
    acts = it.take()
    assert [(a.type, a.value) for a in acts] == [("fill", path), ("click", None)]


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


def test_a_menu_item_read_with_its_menu_open_is_not_the_button_at_its_path() -> None:
    """EBS „File > Save” (the clean-Windows Lite film of 13.10): the screen read while the menu
    was open has the menu first, so the item's path names a toolbar button there. The step is
    still the menu's „Save” (it became „Click “element””, no step saving data), placed where
    the open menu showed it."""
    from maptelo.capture.java import Seen, element_info
    from maptelo.desktop.jab import Node
    from maptelo.desktop.screen import build_screen

    shown = frozenset({"enabled", "showing", "visible"})
    open_menu = build_screen(
        "Wiorek Applications - WRK1",
        1,
        [
            Node("0", "frame", "Wiorek Applications - WRK1", states=shown, box=(0, 0, 1920, 1040)),
            Node("0/0", "popup menu", "", states=shown, box=(0, 56, 180, 140)),
            Node("0/0/0", "menu item", "New", states=shown, box=(2, 60, 176, 24)),
            Node("0/0/1", "menu item", "Save", states=shown, box=(2, 86, 176, 24)),
            Node("0/1", "tool bar", "", states=shown, box=(0, 56, 1920, 40)),
            Node("0/1/0", "push button", "", states=shown, box=(2, 59, 32, 35)),
            Node("0/1/1", "push button", "", states=shown, box=(35, 59, 32, 35)),
        ],
    )
    save = Node("0/1/1", "menu item", "Save", box=(-1, -1, -1, -1))  # its menu closed at once
    info = element_info(Seen(save, [("menu", "File")], 1), open_menu)
    assert (info.role, info.name, info.bbox) == ("menuitem", "Save", (2, 86, 176, 24))
    button = Node("0/1/1", "push button", "", box=(35, 59, 32, 35))  # the button itself
    assert element_info(Seen(button, [], 1), open_menu).role == "button"
    gone = Node("0/1/1", "menu item", "Print", box=(-1, -1, -1, -1))  # not on that screen
    assert (
        element_info(Seen(gone, [], 1), open_menu).role,
        element_info(Seen(gone, [], 1), open_menu).bbox,
    ) == ("menuitem", None)


def test_an_event_java_8_tells_twice_is_one_act() -> None:
    """Java 8's bridge (a 32-bit JRE 8, 13.10) tells a dialog's focus, press and click twice,
    some 10 ms apart: the map clicked the row of a list of values twice. A JDK 21 tells each
    once; the echo is dropped as the events come (the events as Java 8 told them)."""
    lov = [("dialog", "Kontrahenci"), ("frame", "Cennik testowy")]
    rows = "0/0/1/0/0/0/0"
    row = {"role": "label", "name": "K0003 Piekarnia Gamma", "index": 2}
    told = [
        ev("focus", 6.965, "list", "", rows, window=2, chain=lov),
        ev("focus", 6.974, "list", "", rows, window=2, chain=lov),
        ev("active_descendant", 8.431, "list", "", rows, window=2, chain=lov, new=row),
        ev("mouse_pressed", 8.453, "list", "", rows, window=2, chain=lov),
        ev("mouse_pressed", 8.463, "list", "", rows, window=2, chain=lov),
        ev("mouse_clicked", 8.539, "list", "", rows, window=2, chain=lov),
        ev("mouse_clicked", 8.550, "list", "", rows, window=2, chain=lov),
    ]

    def rows_clicked(events: list[dict[str, Any]]) -> list[str]:
        it = Interpreter()
        for event in events:
            it.feed(event)
        it.finish(10.0)
        return [act.seen.node.name for act in it.take() if act.seen is not None]

    assert rows_clicked(told) == ["K0003 Piekarnia Gamma"] * 2  # as the bridge told it
    assert rows_clicked(Echoes().drop(told)) == ["K0003 Piekarnia Gamma"]


def test_a_person_clicking_twice_quickly_is_no_echo() -> None:
    told = [
        ev("mouse_clicked", 1.0, "push button", "Dalej", "0/4"),
        ev("mouse_clicked", 1.12, "push button", "Dalej", "0/4"),  # a quick double click
    ]
    assert Echoes().drop(told) == told
    across = Echoes()  # an echo told in the next batch is dropped too
    assert across.drop(told[:1]) == told[:1]
    assert across.drop([ev("mouse_clicked", 1.008, "push button", "Dalej", "0/4")]) == []


# -- WCR (benchmark M1, M2: a program built like Oracle Forms, Java 8) ------------------------

LINES = [("internal frame", "Cennik – linie: K0010 kontrakt 2026"), ("frame", "WCR 7.1.4")]
REQUEST = [("dialog", "Nowa wersja ceny"), ("frame", "WCR 7.1.4")]


def test_a_combo_box_the_program_sets_with_a_row_is_no_step() -> None:
    """A row of a list of values taken: WCR writes the item, its description and its unit (J.m.)
    into the line. The person never touched J.m.: its value is the program's, not a choice
    (the map asked for a unit no sheet has, and the robot did not start)."""
    item, about, unit = "0/0/1/0/1/14", "0/0/1/0/1/16", "0/0/1/0/1/17"
    it = Interpreter()
    it.feed(ev("text_changed", 14.798, "text", "Indeks", item, chain=LINES, text="26386-F"))
    it.feed(ev("text_changed", 14.823, "text", "Opis", about, chain=LINES, text="Pudło"))
    it.feed(ev("active_descendant", 14.882, "combo box", "J.m.", unit, chain=LINES,
               new={"role": "label", "name": "szt."}))  # fmt: skip
    it.feed(ev("mouse_clicked", 14.89, "push button", "OK", "0/1/2", chain=[("dialog", "Indeksy")]))
    it.feed(ev("focus", 14.944, "combo box", "J.m.", unit, chain=LINES))
    typed(it, 15.4, "Cena", "0/0/1/0/1/18", "6.04")
    it.finish(17.0)
    assert [(a.type, a.seen.node.name if a.seen else None) for a in it.take()] == [
        ("click", "OK"),
        ("fill", "Cena"),
    ]
    chosen = Interpreter()  # the person's own choice in the same box: a step
    chosen.feed(ev("mouse_clicked", 3.0, "combo box", "J.m.", unit, chain=LINES))
    chosen.feed(ev("text_changed", 3.05, "text", "Opis", about, chain=LINES, text="Pudło"))
    chosen.feed(ev("active_descendant", 3.1, "combo box", "J.m.", unit, chain=LINES,
                   new={"role": "label", "name": "kg"}))  # fmt: skip
    chosen.finish(4.0)
    assert [(a.type, a.value) for a in chosen.take()] == [("select", "kg")]


def test_a_field_the_program_emptied_then_typed_as_before_is_typing() -> None:
    """WCR's query mode (F11) empties the block, then the person types the item the line had:
    the screen read before the query showed that item, yet the typing is a step."""
    item = "0/0/1/0/1/7"
    it = Interpreter()
    it.remember(1, {item: "26386-F"}, 6.5)  # the block as it opened, before the query
    it.feed(ev("text_changed", 7.125, "text", "Indeks", item, chain=LINES, text=""))
    it.feed(ev("focus", 7.482, "text", "Indeks", item, chain=LINES, text=""))
    for i, _ in enumerate("26386-F", start=1):
        it.feed(
            ev(
                "text_changed",
                7.5 + 0.01 * i,
                "text",
                "Indeks",
                item,
                chain=LINES,
                text="26386-F"[:i],
            )
        )
    it.feed(ev("focus", 8.15, "text", "Cena", "0/0/1/0/1/11", chain=LINES, text=""))
    it.finish(9.0)
    assert [(a.type, a.value) for a in it.take()] == [("fill", "26386-F")]


def test_a_choice_is_kept_when_the_next_box_opens_at_once() -> None:
    """„Powód zmiany” taken as its list opened (its first row), then „Kanał sprzedaży” opened:
    the first box's choice is a step before the second's (benchmark M1 lost it)."""
    reason, channel = "0/0/1/0/0/16", "0/0/1/0/0/18"
    it = Interpreter()
    it.feed(ev("mouse_clicked", 11.221, "combo box", "Powód zmiany", reason, chain=REQUEST))
    it.feed(ev("active_descendant", 11.284, "combo box", "Powód zmiany", reason, chain=REQUEST,
               new={"role": "label", "name": "Negocjacje handlowe", "index": 0}))  # fmt: skip
    it.feed(ev("active_descendant", 11.917, "combo box", "Kanał sprzedaży", channel, chain=REQUEST,
               new={"role": "label", "name": "Sklep", "index": 0}))  # fmt: skip
    it.feed(ev("mouse_clicked", 11.926, "combo box", "Kanał sprzedaży", channel, chain=REQUEST))
    it.feed(ev("active_descendant", 12.052, "combo box", "Kanał sprzedaży", channel, chain=REQUEST,
               new={"role": "label", "name": "Hurt", "index": 1}))  # fmt: skip
    it.finish(13.0)
    assert [(a.type, a.value) for a in it.take()] == [
        ("select", "Negocjacje handlowe"),
        ("select", "Hurt"),
    ]


def test_a_value_typed_into_a_combo_box_is_one_step() -> None:
    """WCR's Waluta takes typing and completes it (EU: EUR); the box then says EUR is chosen:
    the typing is the step, not a choice besides it."""
    box, editor = "0/0/1/0/0/9", "0/0/1/0/0/9/1"
    it = Interpreter()
    typed(it, 7.9, "Waluta", editor, "EUR")
    it.feed(ev("active_descendant", 8.099, "combo box", "Waluta", box, chain=FRAME,
               new={"role": "label", "name": "EUR"}))  # fmt: skip
    it.feed(ev("focus", 8.2, "text", "Nowa cena netto", "0/0/1/0/0/11"))
    it.finish(9.0)
    assert [(a.type, a.value) for a in it.take()] == [("fill", "EUR")]


def test_a_swing_list_s_row_is_read_when_the_bridge_tells_its_selection(tmp_path) -> None:
    """A Swing list (WCR's Navigator, „Funkcje”) tells only that its selection changed: the
    recorder reads the row chosen, and the click on the list is a click on that row."""
    from types import SimpleNamespace

    from maptelo.capture.java import JavaRecorder, JavaRecorderOptions
    from maptelo.desktop.jab import Node

    nav = [("internal frame", "Nawigator – WCR"), ("frame", "WCR 7.1.4")]
    functions = "0/0/1/0/0/0/0/1/0/0/0/0"
    told = [ev("selection_changed", 1.475, "list", "Funkcje", functions, chain=nav)]
    for event in told:
        event["source"]["node"]["children"] = 6
    told += [
        ev("mouse_pressed", 1.492, "list", "Funkcje", functions, chain=nav),
        ev("mouse_clicked", 1.527, "list", "Funkcje", functions, chain=nav),
    ]
    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    rec.bridge = SimpleNamespace(
        events=lambda: told,
        children_selected=lambda hwnd, path, count: [0] if path == functions else [],
        node=lambda hwnd, path: (
            Node(path, "label", "Cenniki", states=frozenset({"showing"}), box=(1, 1, 9, 9))
            if path == functions + "/0"
            else None
        ),
    )
    rec._window_of = lambda source, t=None: 1  # type: ignore[method-assign]
    events = rec._take_events()
    assert [e["kind"] for e in events] == [
        "selection_changed",
        "active_descendant",
        "mouse_pressed",
        "mouse_clicked",
    ]
    it = Interpreter()
    for event in events:
        it.feed(event)
    it.finish(3.0)
    [act] = it.take()
    assert (act.type, act.seen.node.name if act.seen else None) == ("click", "Cenniki")


def test_a_row_of_a_list_of_values_taken_with_the_keys_is_a_step() -> None:
    """A person at Oracle Forms keeps to the keys: the arrows to the item's row in the list of
    values, then Enter. The row is the step, as a click on it would be; the arrows and the Enter
    pressed on another day would take another record's row (benchmark M2, the keys way)."""
    lov = [("dialog", "Indeksy"), ("frame", "WCR 7.1.4")]
    table = "0/0/0/1/0/1/0/0"
    it = Interpreter()
    it.feed(ev("focus", 14.12, "table", "Indeksy", table, chain=lov))
    for n, row in enumerate(["12187-H", "15380-F", "26386-F"]):
        it.feed({"kind": "key", "t": 14.2 + 0.1 * n, "key": "ArrowDown"})
        it.feed(ev("active_descendant", 14.21 + 0.1 * n, "table", "Indeksy", table, chain=lov,
                   new={"role": "label", "name": row, "index": n + 1}))  # fmt: skip
    it.feed({"kind": "key", "t": 14.6, "key": "Enter"})
    it.finish(15.0)
    [act] = it.take()
    assert (act.type, act.seen.node.name if act.seen else None, act.cell) == (
        "click",
        "Indeksy",
        "26386-F",
    )


def test_a_menu_command_after_a_click_that_opened_a_form_is_on_that_form(tmp_path):
    """WCR's Znajdź opens the price list's lines over the find window: Zapytanie > Wprowadź
    zapytanie chosen next is for the lines, not for the find window under them (benchmark M2
    r2: the command's screen was the find window, and every row stopped on it)."""
    from types import SimpleNamespace

    from maptelo.capture.java import Act, JavaRecorder, JavaRecorderOptions, Seen
    from maptelo.desktop.jab import Node, Window
    from maptelo.desktop.screen import build_screen

    shown = frozenset({"enabled", "showing", "visible"})
    lines = "Cennik – linie: K0010 kontrakt 2026"
    main = Window(1, "WCR 7.1.4 – Wiórek Ceny i Rozliczenia", 7, True)
    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    rec.app = "wcr"
    rec._windows = {1: main}
    written = []
    rec.writer = SimpleNamespace(write=written.append)
    screen = build_screen(
        main.title,
        1,
        [
            Node("0", "frame", main.title, states=shown, box=(0, 0, 1180, 760)),
            Node("0/1", "internal frame", "Znajdź cennik", states=shown, box=(20, 60, 400, 200)),
            Node("0/1/0", "push button", "Znajdź", states=shown, box=(30, 200, 70, 26)),
            Node("0/2", "internal frame", lines, states=shown, box=(300, 40, 800, 500)),
        ],
    )
    rec._state_screens = {"s004": screen}
    rec._screens = {1: screen}
    rec._worked_in, rec._worked_at = "Znajdź cennik", 4.9  # its Znajdź was clicked
    rec._note_frames(
        [
            {
                "kind": "child_changed",
                "t": 4.88,  # told between the press and the click of Znajdź (M2 r3)
                "old": None,
                "new": {"role": "internal frame", "name": lines},
            }
        ]
    )
    query = Seen(Node("0/0/1/0/1", "menu item", "Wprowadź zapytanie"), [("frame", main.title)], 1)
    rec._write_act(Act("click", 5.9, query, menu="Zapytanie"), "s004", "s005")
    assert written[-1].url == "java://wcr/Cennik – *"  # the lines' form (its record left out)
    rec._worked_in, rec._worked_at = lines, 6.6  # typed into the lines since: nothing new opened
    rec._write_act(Act("click", 8.8, query, menu="Zapytanie"), "s004", "s006")
    assert written[-1].url == "java://wcr/Cennik – *"


def test_a_row_double_clicked_in_a_list_that_closed_at_once_is_read_from_the_screen_before(
    tmp_path,
) -> None:
    """WCR's „Indeksy”: a double click takes the row and closes the list at once, before the
    recorder can read the table (benchmark M2 r2: „click table Indeksy” without its row, so the
    step was not the one the click-and-OK recordings made). The table as the screen before the
    click showed it, and the cell the table told chosen, give the row."""
    from types import SimpleNamespace

    from maptelo.capture.java import JavaRecorder, JavaRecorderOptions
    from maptelo.desktop.jab import Table

    lov = "0/0/0/1/0/1/0/0"
    chain = [("dialog", "Indeksy"), ("frame", "WCR 7.1.4 – Wiórek Ceny i Rozliczenia")]
    it = Interpreter()
    it.feed(ev("active_descendant", 12.501, "table", "Indeksy", lov, chain=chain,
               new={"role": "label", "name": "31830-E", "index": 3}))  # fmt: skip
    it.feed(ev("mouse_pressed", 12.514, "table", "Indeksy", lov, chain=chain))
    it.feed(ev("mouse_clicked", 12.544, "table", "Indeksy", lov, chain=chain))
    it.finish(13.0)
    acts = it.take()
    assert [(a.type, a.cell, a.told_index) for a in acts] == [("click", "31830-E", 3)]
    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    rec.bridge = SimpleNamespace(table=lambda window, path: None)  # the list is gone
    before = Table(
        ["Indeks", "Opis", "J.m."],
        [
            ["31830-D", "Pudło fasonowe 250x250x100", "szt."],
            ["31830-E", "Pudło fasonowe 300x300", "szt."],
        ],
    )
    rec._last_screen = SimpleNamespace(hwnd=1, tables={lov: before})  # type: ignore[assignment]
    act = acts[0]
    rec._row_of(act)
    assert act.row is not None
    assert (act.row.table, act.row.index, act.row.cells["Indeks"]) == ("Indeksy", 1, "31830-E")
    assert act.column == "Indeks"


def test_a_double_click_that_closes_its_list_is_one_though_told_in_the_owner_s_window() -> None:
    """WCR's „Indeksy”: the double click takes the row and closes the list. When the bridge
    tells the second click the list's window is gone, so it is told in WCR's main window that
    owns the list (benchmark M2, 18.10: taken for a single click, the line read before WCR put
    the choice in, and the robot's „Cena” found in two rows). The same dialog around it."""
    chain = [("dialog", "Indeksy"), ("frame", "WCR 7.1.4 – Wiórek Ceny i Rozliczenia")]
    first, second = "0/0/1/0/1/0/0", "0/0/0/1/0/1/0/0"  # the list's tree changes as it closes
    it = Interpreter()
    it.feed(ev("active_descendant", 14.947, "table", "Indeksy", first, chain=chain, window=7,
               new={"role": "label", "name": "12187-H", "index": 0}))  # fmt: skip
    it.feed(ev("mouse_pressed", 14.948, "table", "Indeksy", first, chain=chain, window=7))
    it.feed(ev("mouse_clicked", 14.950, "table", "Indeksy", first, chain=chain, window=7))
    it.feed(ev("mouse_pressed", 15.091, "table", "Indeksy", second, chain=chain, window=1))
    it.feed(ev("mouse_clicked", 15.103, "table", "Indeksy", second, chain=chain, window=1))
    it.finish(16.0)
    [act] = it.take()
    assert (act.type, act.cell, act.clicks) == ("click", "12187-H", 2)


def test_the_cell_double_clicked_to_edit_is_the_one_the_table_told_not_its_twin(
    tmp_path,
) -> None:
    """SRK's „Nowa korekta”: before the edit „Ilość przed” and „Ilość po” both show 371. The
    table told the cell clicked (place 5, „Ilość po”); taken by its text, the double click was on
    „Ilość przed”, not the cell then typed into, and became a step of its own („Otwórz wiersz…
    (dwuklikiem)”) that no rule explained (benchmark D04 1/9, 18.10). A cell told in another
    row than the one chosen is an old one: the text names the column then."""
    from types import SimpleNamespace

    from maptelo.capture.java import Act, JavaRecorder, JavaRecorderOptions
    from maptelo.desktop.jab import Table

    lines = "0/0/1/0/1/0/0/1/0/1/0/0"
    chain = [("internal frame", "Nowa korekta"), ("frame", "SRK 4.2.7")]
    it = Interpreter()
    it.feed(ev("active_descendant", 4.028, "table", "Pozycje korekty", lines, chain=chain,
               new={"role": "label", "name": "371", "index": 5}))  # fmt: skip
    it.feed(ev("mouse_pressed", 4.029, "table", "Pozycje korekty", lines, chain=chain))
    it.feed(ev("mouse_clicked", 4.032, "table", "Pozycje korekty", lines, chain=chain))
    it.finish(5.0)
    [act] = it.take()
    assert (act.type, act.cell, act.told_index) == ("click", "371", 5)
    headers = ["Lp", "Indeks", "Nazwa", "Ilość przed", "Cena przed", "Ilość po", "Cena po", "Netto"]
    row = ["1", "52957-C", "Przekładka 780x580", "371", "0,76", "371", "0,76", "0,00"]
    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    rec.bridge = SimpleNamespace(table=lambda window, path: Table(headers, [row], selected=[0]))
    rec._row_of(act)
    assert act.row is not None
    assert (act.row.index, act.column, act.cell) == (0, "Ilość po", "371")

    told_before = Act("click", 6.0, act.seen, cell="371", told_index=13)  # row 1's „Ilość po”
    rec._row_of(told_before)
    assert told_before.column == "Ilość przed"


def test_a_swing_status_line_shows_its_message_as_its_name() -> None:
    """A Swing label tells the bridge no text unless it is HTML: its message is its name (WCR's
    status line once it no longer hid its messages under a name of its own)."""
    from maptelo.desktop.jab import Node
    from maptelo.desktop.screen import build_screen

    shown = frozenset({"enabled", "showing", "visible"})
    said = "FRM-40400: Transakcja zakończona: zapisano rekordów: 2."
    nodes = [
        Node("0", "frame", "WCR", states=shown, box=(0, 0, 1000, 700)),
        Node("0/1", "label", said, states=shown, box=(6, 680, 900, 18)),
    ]
    screen = build_screen("WCR", 1, nodes)
    assert screen.status == [said]
    assert f"- status: {said}" in screen.aria()


def test_a_question_s_button_told_without_its_window_is_in_the_question_opened_last(
    tmp_path,
) -> None:
    """Java 8's bridge told „Tak” of WCR's question as the question closed: no window, only
    the option pane around it (benchmark M1 r2). Its window is the dialog opened last before
    the click, not none (a step of no window was a decision nobody could explain)."""
    from maptelo.capture.java import JavaRecorder, JavaRecorderOptions
    from maptelo.desktop.jab import Window

    main = Window(1, "WCR 7.1.4 – Wiórek Ceny i Rozliczenia", 7, True)
    calendar = Window(8, "Kalendarz", 7, True, owner=1)
    question = Window(9, "WCR – pytanie", 7, True, owner=1)
    rec = JavaRecorder(tmp_path, JavaRecorderOptions())
    rec.main = main
    rec._windows = {1: main}  # the question has closed
    rec._ever = {1: main, 8: calendar, 9: question}
    rec._opened_at = {1: 0.0, 8: 10.2, 9: 12.4}
    source = {
        "node": {"role": "push button", "name": "Tak"},
        "chain": [["option pane", ""]],
        "window": 0,
    }
    assert rec._window_of(source, 14.2) == 9
    assert rec._window_of(dict(source, chain=[]), 14.2) == 0  # nothing says it was a question


def test_a_row_double_clicked_is_one_click_of_two() -> None:
    """WCR's „Wnioski do akceptacji”: the request opens with a double click on its row. Its
    second click is no step of its own, and the step is a double click (benchmark M4 r1: the
    robot clicked once and nothing opened)."""
    table = "0/0/1/0/1/0/0"
    chain = [("internal frame", "Akceptacje wniosków"), ("frame", "WCR")]
    it = Interpreter()
    it.feed(ev("active_descendant", 3.0, "table", "Wnioski do akceptacji", table, chain=chain,
               new={"role": "label", "name": "WC/2026/000104", "index": 0}))  # fmt: skip
    it.feed(ev("mouse_pressed", 3.01, "table", "Wnioski do akceptacji", table, chain=chain))
    it.feed(ev("mouse_clicked", 3.03, "table", "Wnioski do akceptacji", table, chain=chain))
    it.feed(ev("mouse_pressed", 3.17, "table", "Wnioski do akceptacji", table, chain=chain))
    it.feed(ev("mouse_clicked", 3.19, "table", "Wnioski do akceptacji", table, chain=chain))
    it.finish(4.0)
    acts = it.take()
    assert [(a.type, a.clicks) for a in acts] == [("click", 2)]
    assert (acts[0].t, acts[0].end) == (3.03, 3.19)  # over at its second click
    once = Interpreter()  # one click, and another a second later: two clicks
    once.feed(ev("mouse_clicked", 1.0, "table", "Wnioski do akceptacji", table, chain=chain))
    once.feed(ev("mouse_clicked", 2.0, "table", "Wnioski do akceptacji", table, chain=chain))
    once.finish(3.0)
    assert [a.clicks for a in once.take()] == [1, 1]


def test_the_screen_after_a_double_click_is_read_after_its_second_click() -> None:
    """Benchmark M2 r8: the list of values closed by a double click; WCR put the chosen Indeks
    and its Opis into the line 10 to 30 ms after the second click, and the person typed the price
    half a second later. The second click counted as the person going on, so the screen after
    the double click was read as of it: the line still had the typed pattern and no Opis, and
    the price's row rule named no row of an item already in the price list."""
    from maptelo.capture.java import Act, JavaRecorder

    rec: Any = JavaRecorder.__new__(JavaRecorder)
    double = Act("click", 13.614, None, clicks=2, ended=13.759)
    price = Act("fill", 14.603, None, value="5.30")
    rec._pending = [(double, "s010"), (price, "s010")]
    rec._human = [13.601, 13.614, 13.739, 13.759, 14.501, 14.526]
    rec._human_windows = {}
    rec._windows = {}
    rec._captured_at = 0.0
    read: list[float] = []
    written: list[tuple[str, str, str]] = []
    rec._refresh_windows = lambda: None
    rec._front_window = lambda since: 1
    rec._capture = lambda hwnd, until: read.append(until) or "s011"
    rec._write_act = lambda act, before, after: written.append((act.type, before, after))
    assert rec._settle_earlier() == 1
    assert read == [14.501]  # the price's press, not the double click's own second click
    assert written == [("click", "s010", "s011")]
    assert rec._pending == [(price, "s011")]


def test_a_screen_not_read_is_told_in_the_raw_events() -> None:
    """Java's file chooser never had a screen in benchmark M3 r3: the window that could not be
    read, and why, is kept for whoever reads the raw events."""
    from types import SimpleNamespace

    from maptelo.capture.java import JavaRecorder
    from maptelo.desktop.jab import Window

    def broken(hwnd: int, **_: object) -> None:
        raise RuntimeError("the window went away")

    recorder = JavaRecorder.__new__(JavaRecorder)
    recorder.bridge = SimpleNamespace(tree=broken, clock=lambda: 3.0)  # type: ignore[assignment]
    recorder._windows = {7: Window(7, "Otwórz plik cennika", 1, True)}
    recorder._ever = {}
    recorder._buffer = []
    assert recorder._screen(7) is None
    assert recorder._screen(8) is None
    told = [(e["kind"], e["title"], e["why"]) for e in recorder._buffer]
    assert told == [
        ("screen_unread", "Otwórz plik cennika", "RuntimeError: the window went away"),
        ("screen_unread", None, "not among the program's windows"),
    ]


def test_a_double_click_whose_window_changed_between_its_clicks_is_one() -> None:
    """Benchmark M4 r4: the first click of the double click on the request's row opened its
    frame in the same window, and the bridge told the second click on the list's table at
    another place (M3 r4: the list of values closing). The same table, named so: one double
    click, not two steps (the robot was then stopped at the second as a decision)."""
    chain = [("internal frame", "Akceptacje wniosków"), ("frame", "WCR")]
    name = "Wnioski do akceptacji"
    it = Interpreter()
    it.feed(ev("mouse_pressed", 3.00, "table", name, "0/0/1/0/0/0/0/1/0/1/0/0", chain=chain))
    it.feed(ev("mouse_clicked", 3.03, "table", name, "0/0/1/0/0/0/0/1/0/1/0/0", chain=chain))
    it.feed(ev("mouse_pressed", 3.17, "table", name, "0/0/1/0/0/1/0/1/0/1/0/0", chain=chain))
    it.feed(ev("mouse_clicked", 3.19, "table", name, "0/0/1/0/0/1/0/1/0/1/0/0", chain=chain))
    it.finish(4.0)
    assert [(a.type, a.clicks) for a in it.take()] == [("click", 2)]
    other = Interpreter()  # another table of the window, named otherwise: two clicks
    other.feed(ev("mouse_clicked", 3.03, "table", name, "0/0/1/0/0/0/0/1/0/1/0/0", chain=chain))
    other.feed(ev("mouse_clicked", 3.19, "table", "Linie", "0/0/1/0/0/0/0/1/0/2/0/0", chain=chain))
    other.finish(4.0)
    assert [a.clicks for a in other.take()] == [1, 1]
