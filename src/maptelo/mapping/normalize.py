"""From raw trace events to logical actions ("acts").

In a single recording this recognises:
- **login** at the start (a secret was typed): a precondition, not a process step;
- **interrupts**: a dialog that appeared by itself after the page loaded and was dismissed
  (a session popup), as opposed to a dialog the previous action opened on purpose;
- **corrected attempts**: an action rejected with an error message and repeated after the
  person re-entered values; the error becomes a known exception of that action;
- **noise**: clicks on non-interactive elements, a field filled twice in a row.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
from typing import Any, Literal
from urllib.parse import urlsplit

from maptelo.calendars import days_of, numbered_days
from maptelo.dates import find_day, read_day, read_month
from maptelo.mapping.shown import ANY_WORD
from maptelo.model.urls import origin
from maptelo.trace.aria import parse_aria
from maptelo.trace.locators import candidates_for
from maptelo.trace.schema import CalendarSeen, ElementInfo, RowContext, Trace, TraceEvent

_HELP_MARK = re.compile(r"(?<=\w)\?$")
_PLAIN_ID = re.compile(r"[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*")
"""An id or a form name a person could read as the field's name (``username``, ``first-name``);
not ``S2BVXXE`` nor ``product[status]``."""

Role = Literal["step", "login", "interrupt", "noise", "superseded"]

_INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "summary", "label", "option"}
_INTERACTIVE_ROLES = {
    "button", "link", "checkbox", "radio", "menuitem", "tab", "option", "switch",
    "textbox", "combobox", "searchbox", "spinbutton",
}  # fmt: skip
_ENTRY = ("fill", "select", "check", "uncheck")
INTERRUPT_DELAY_S = 0.3


@dataclass
class Attempt:
    """An earlier try of an action that the application rejected with a message."""

    message: str
    values: dict[str, str]
    event_seqs: list[int]
    role: str = "alert"
    """How the application said it: an alert, or a status line."""


@dataclass
class DatePick:
    """A day picked in a calendar: which day, how the calendar names its days and month,
    what opens it (or the calendar itself, always shown), what moves it."""

    day: date
    pattern: str
    days: dict[str, str]
    month: str | None
    target: ElementInfo
    opens: bool
    label: str
    box: ElementInfo | None = None
    next: ElementInfo | None = None
    previous: ElementInfo | None = None
    seqs: list[int] = field(default_factory=list)
    field_used: ElementInfo | None = None
    """The text field used last before the day was clicked (the calendar may be its)."""


@dataclass
class Act:
    event: TraceEvent
    observed: list[TraceEvent] = field(default_factory=list)
    role: Role = "step"
    attempts: list[Attempt] = field(default_factory=list)
    chosen: TraceEvent | None = None
    """For a value typed into a field with suggestions: the suggestion then picked."""
    picked: DatePick | None = None
    """For a day clicked in a calendar: the date picked, with what opened and moved it."""
    item: str | None = None
    """For a field named for an item („Przyjęto: 37241-E”): the item's code in this recording."""
    calendar_unread: bool = False
    """A day clicked among the days of a calendar that could not be read (two months of
    plain numbers): it stays a click on the same day, and the mapping says so."""

    @property
    def seq(self) -> int:
        return self.event.seq

    @property
    def kind(self) -> str:
        return self.event.type

    @property
    def field_name(self) -> str | None:
        """The field as people call it: a help mark after the label ("Product?") is not
        read as part of its name. A field nothing on the screen names is called as the page
        calls it, when that is a plain word (``id="password"``): two such fields stay two
        fields (MiniWoB++ login-user), and a made-up id („S2BVXXE”) names nothing."""
        target = self.event.target
        if target is None:
            return None
        label = target.label or target.name or target.placeholder or target.column or target.beside
        if not label and self.event.type in ("fill", "select"):
            plain = (w for w in (target.field, target.id) if w and _PLAIN_ID.fullmatch(w))
            label = next(plain, None)
        if not label:
            return None
        label = label.removesuffix(": " + ANY_WORD)  # the field of the item: „Przyjęto”
        return _HELP_MARK.sub("", label) or label

    def appeared(self, *roles: str, window: int | None = None) -> list[TraceEvent]:
        """What appeared after the act with one of ``roles`` (``window``: in that window)."""
        return [
            o
            for o in self.observed
            if o.type == "appeared"
            and o.target
            and o.target.role in roles
            and (window is None or o.window == window)
        ]

    def navigated_to(self, window: int | None = None) -> str | None:
        urls = [
            o.url
            for o in self.observed
            if o.type == "navigated" and o.url and (window is None or o.window == window)
        ]
        return urls[-1] if urls else None


@dataclass
class Normalized:
    trace: Trace
    acts: list[Act]
    start_url: str

    @property
    def steps(self) -> list[Act]:
        return [a for a in self.acts if a.role == "step"]

    def by_role(self, role: Role) -> list[Act]:
        return [a for a in self.acts if a.role == role]


def _path(url: str | None) -> str:
    return urlsplit(url or "").path


def _same_target(a: Act, b: Act) -> bool:
    ta, tb = a.event.target, b.event.target
    if ta is None or tb is None:
        return ta is tb and a.event.value == b.event.value
    if (ta.role, ta.name, ta.label, ta.column) != (tb.role, tb.name, tb.label, tb.column):
        return False
    if ta.field and tb.field and ta.field != tb.field:
        return False  # "Password" and its confirmation: the same words, two fields
    if not (ta.name or ta.label or ta.column):  # nothing names it: compare where it is
        return ta.css == tb.css
    return True


_HANDOFF = re.compile(
    r"(?:^|&)(?:code|state|session_state|id_token|access_token|samlresponse|samlrequest|"
    r"relaystate|ticket)=",
    re.IGNORECASE,
)
"""What a sign-in service hands back in the address: such a page is reached through it, not
opened by the person."""


def group_acts(trace: Trace) -> list[Act]:
    """Each action with what followed it. A person who goes to another application (types
    its address, uses a bookmark) clicks nothing: the recording sees only the page change,
    after the screen had settled. That change is the person's own step, opening the other
    application, not a result of the action before it."""
    acts: list[Act] = []
    page: str | None = None
    said = [event for event in trace.events if event.type == "note"]
    for event in trace.events:
        if event.type == "note":
            continue  # by its time below: a recorder may write it before an earlier act
        if event.is_action:
            acts.append(Act(event))
        elif acts and _opened_by_person(acts[-1], event, page, trace):
            acts.append(Act(event.model_copy(update={"type": "navigate", "value": event.url})))
        elif acts:
            acts[-1].observed.append(event)
        page = event.url or page
    for note in said:  # what the person said goes with the act they had just done (or the first)
        before = [act for act in acts if act.event.t <= note.t]
        owner = before[-1] if before else (acts[0] if acts else None)
        if owner is not None:
            owner.observed.append(note)
    return acts


def _opened_by_person(act: Act, event: TraceEvent, page: str | None, trace: Trace) -> bool:
    """A page of another application, shown after the screen had settled from ``act``."""
    if event.type != "navigated" or not event.url or page is None:
        return False
    if event.window != act.event.window:
        return False  # a window the process opened shows its pages by itself
    settled = act.event.state_after
    shown = trace.state(settled)
    if shown is not None and shown.window != event.window:
        # the act opened another window (the label's PDF in a tab of its own, benchmark p10):
        # its own window stayed as it was before it
        settled = act.event.state_before
    if event.state_before is None or event.state_before != settled:
        return False  # the action's own result: a link, a redirect, a form sent
    if origin(event.url) == origin(page) and _section(event.url) == _section(page):
        # within one part of an application a page may change by itself after a while (back
        # to the list after a save); another part of it, reached with nothing clicked, is the
        # person's own step: a typed address, a bookmark (benchmark P20 mixed: /odbiory typed
        # on /szkody, where the others click "Odbiory" in the menu)
        return False
    parts = urlsplit(event.url)
    return not (_HANDOFF.search(parts.query) or _HANDOFF.search(parts.fragment))


def _section(url: str) -> str:
    """The part of an application a page belongs to: the first word of its path."""
    path = urlsplit(url).path.strip("/")
    return path.split("/", 1)[0].casefold()


_ONE_TIME_WORDS = re.compile(
    r"aplikacj|authenticator|uwierzytel|jednorazow|one.?time|weryfikac|verification|\bsms\b"
    r"|\botp\b|\btotp\b|\b2fa\b|\btoken\b",
    re.IGNORECASE,
)
_CODE = re.compile(r"^\d{4,8}$")


def one_time_code(act: Act) -> bool:
    """A code from a phone app or a text message: it is new every time, so a robot cannot
    know it (the field says so, or its label speaks of the app and the person typed digits)."""
    target = act.event.target
    if act.kind != "fill" or target is None:
        return False
    if (target.autocomplete or "").lower() == "one-time-code":
        return True
    label = " ".join(filter(None, (target.label, target.name, target.placeholder)))
    return bool(_ONE_TIME_WORDS.search(label)) and bool(_CODE.match(act.event.value or ""))


_SIGN_IN_FIELDS = 3
"""A sign-in screen asks for a name and a password (sometimes a company too), nothing more."""


def _mark_login(trace: Trace, acts: list[Act]) -> str | None:
    """Mark a sign-in at the start, and at the start of each other application the person
    opened; returns the URL where the process proper begins. An application opened and
    signed in to is opened where the sign-in led (a robot comes with its session)."""
    opened = [i for i, a in enumerate(acts) if a.kind == "navigate"]
    if not opened or opened[0] != 0:
        opened.insert(0, 0)
    start: str | None = None
    for number, begin in enumerate(opened):
        end = opened[number + 1] if number + 1 < len(opened) else len(acts)
        landed = _sign_in(trace, acts[begin:end], at_start=number == 0)
        if number == 0:
            start = landed
        elif landed is not None:
            event = acts[begin].event
            acts[begin].event = event.model_copy(update={"value": landed, "url": landed})
    return start


def _sign_in(trace: Trace, acts: list[Act], *, at_start: bool) -> str | None:
    """Mark a sign-in at the start of these acts; returns where it led. Only a sign-in
    screen counts: a password typed into the work itself (a new customer's account, a
    password typed twice) is a step of the process, with a secret input. ``at_start``: the
    recording's own start (else the acts begin with opening another application, which stays
    a step)."""
    if not acts:
        return None
    secret = next((i for i, a in enumerate(acts) if a.kind == "fill" and a.event.secret), None)
    if secret is None:
        return _sign_in_filled_for_you(trace, acts, at_start=at_start)
    submit = next(
        (
            i
            for i in range(secret + 1, len(acts))
            if acts[i].kind in ("click", "press") and acts[i].navigated_to()
        ),
        None,
    )
    if submit is None:
        return None
    login_page = _path(acts[secret].event.url)
    if any(a.kind != "navigate" and _path(a.event.url) != login_page for a in acts[:secret]):
        return None  # work was done before the password: a password in the work (an account)
    on_page = [a for a in acts[:submit] if _path(a.event.url) == login_page]
    typed = [a for a in on_page if a.kind in ("fill", "select")]
    if len(typed) > _SIGN_IN_FIELDS or sum(a.event.secret for a in typed) > 1:
        return None  # a form with many fields, or a password typed twice: a new account
    second = _second_factor(acts, submit)  # a code from the phone after the password
    end = second if second is not None else submit
    for index, act in enumerate(acts[: end + 1]):
        if index == 0 and not at_start:
            continue  # opening the other application: a step, done where the sign-in led
        if act.kind == "navigate" or _path(act.event.url) in (
            login_page,
            _path(acts[end].event.url),
        ):
            act.role = "login"
    return acts[end].navigated_to()


_SIGN_IN_BUTTON = re.compile(
    r"^(?:zaloguj(?: się)?|logowanie|log ?in|sign ?in|login|anmelden|wejdź)$", re.IGNORECASE
)
_PASSWORD_FIELD = re.compile(r"has[łl]o|password|passwort|kennwort|mot de passe", re.IGNORECASE)


def _sign_in_filled_for_you(trace: Trace, acts: list[Act], *, at_start: bool) -> str | None:
    """A sign-in whose password a password manager typed: the recording saw no secret, only
    a name typed (or nothing) and "Zaloguj" clicked on a screen with a password field. Taken
    for work, the name became data the sheet does not have (benchmark: login_as_input)."""
    submit = next(
        (i for i, a in enumerate(acts) if a.kind in ("click", "press") and a.navigated_to()),
        None,
    )
    if submit is None:
        return None
    pressed = acts[submit]
    button = pressed.event.target
    words = " ".join(((button.name or button.text or "") if button else "").split())
    if pressed.kind == "click" and not _SIGN_IN_BUTTON.match(words):
        return None
    before = acts[:submit]
    page = _path(pressed.event.url)
    if any(a.kind not in ("navigate", "fill", "press") for a in before):
        return None  # something else was done first: this is work
    typed = [a for a in before if a.kind == "fill"]
    if len(typed) > 2 or any(_path(a.event.url) != page for a in typed):
        return None
    state = trace.state(pressed.event.state_before)
    screen = parse_aria(state.aria) if state is not None else None
    asks = screen is not None and any(
        n.role == "textbox" and _PASSWORD_FIELD.search(n.name or "") for n in screen.walk()
    )
    if not asks:
        return None
    for index, act in enumerate(acts[: submit + 1]):
        if index == 0 and not at_start:
            continue  # opening the other application: a step, done where the sign-in led
        act.role = "login"
    return pressed.navigated_to()


def _second_factor(acts: list[Act], submit: int) -> int | None:
    """The page after the password that asks for a code from the phone: where its submit is."""
    following = acts[submit + 1 :]
    if not following or not one_time_code(following[0]):
        return None
    page = _path(following[0].event.url)
    for index, act in enumerate(following, start=submit + 1):
        if _path(act.event.url) != page:
            return None
        if act.kind in ("click", "press") and act.navigated_to():
            return index
    return None


def _mark_interrupts(trace: Trace, acts: list[Act]) -> None:
    for index, act in enumerate(acts):
        target = act.event.target
        if target is None or target.dialog is None or index == 0:
            continue
        previous = acts[index - 1]
        shown = next(
            (
                o
                for o in previous.appeared("dialog", "alertdialog")
                if o.target and o.target.name == target.dialog
            ),
            None,
        )
        if shown is None:
            continue
        loads = [o.t for o in previous.observed if o.type == "navigated" and o.t <= shown.t]
        reference = loads[-1] if loads else previous.event.t
        state = trace.state(previous.event.state_after)
        on_screen = state is not None and parse_aria(state.aria).find("dialog", target.dialog)
        if shown.t - reference >= INTERRUPT_DELAY_S and not on_screen:
            act.role = "interrupt"


_CHOSEN_ROLES = {"button", "link", "menuitem", "tab", "option", "checkbox", "radio", "switch"}


def _selected_to_copy(steps: list[Act]) -> None:
    """Clicks that only selected the words copied right after them (a double or a triple
    click on a cell's text, then Ctrl+C): selecting, not a step. A click that opened or showed
    something, or one on a button, a link or a field, stays a step."""
    run: list[Act] = []
    for act in steps:
        target = act.event.target
        quiet = act.navigated_to() is None and not any(o.type == "appeared" for o in act.observed)
        if (
            act.kind != "click"
            or target is None
            or not quiet
            or act.picked is not None
            or target.tag in _INTERACTIVE_TAGS
            or target.role in _CHOSEN_ROLES
        ):
            run = []
            continue
        run.append(act)
        words = " ".join((target.name or target.text or "").split())
        copied = [" ".join((o.value or "").split()) for o in act.observed if o.type == "copied"]
        if any(c and c in words for c in copied):
            for clicked in run:
                same = clicked.event.target
                if same is not None and " ".join((same.name or same.text or "").split()) == words:
                    clicked.role = "noise"
            run = []


def _mark_noise(acts: list[Act]) -> None:
    steps = [a for a in acts if a.role == "step"]
    _selected_to_copy(steps)
    for act in steps:
        target = act.event.target
        if act.kind == "click" and target is not None and act.picked is None:
            interactive = (
                target.tag in _INTERACTIVE_TAGS
                or target.role in _INTERACTIVE_ROLES
                or bool(target.pointer)  # a hand over it: the page made it to be clicked
            )
            # a row of a table chosen (a list window's search result): only the choice changes
            # (benchmark D05: the invoice picked before OK was taken for a stray click)
            interactive = interactive or (
                target.role in ("cell", "gridcell", "row") and target.row is not None
            )
            had_effect = act.navigated_to() is not None or any(
                o.type == "appeared" for o in act.observed
            )
            if not interactive and not target.testid and not had_effect:
                act.role = "noise"  # a stray click on text that changed nothing
    for earlier, later in pairwise(steps):
        if earlier.kind == "fill" and later.kind == "fill" and _same_target(earlier, later):
            earlier.role = "noise"
        a, b = earlier.event.target, later.event.target
        if (
            earlier.kind == "click"
            and later.kind == "fill"
            and (earlier.event.url or "").startswith("java:")
            and a is not None
            and b is not None
            and a.role == b.role == "cell"
            and a.column
            and a.column == b.column
            and a.row is not None
            and b.row is not None
            and _same_record(a.row, b.row, a.column)
            and a.row.index == b.row.index
            and (not a.row.table or not b.row.table or a.row.table == b.row.table)
            and a.dialog == b.dialog
            and earlier.event.url == later.event.url
            and earlier.event.window == later.event.window
            and 0 <= later.event.t - earlier.event.t <= _CELL_EDIT_S
        ):
            # Opening a JTable editor is part of filling that cell. Keeping it
            # as a row-selection step can mistake the new amount for its key.
            earlier.role = "noise"


_SHOWED = ("appeared", "navigated", "downloaded", "dialog")
"""What an act showed: a box ticked that showed something is a step of its own."""


def _merge_box_toggles(acts: list[Act]) -> None:
    """The same box ticked and unticked in turn, nothing shown in between, is one step: its
    last state. A click on it told after the state it gave is that state too (else: unticked,
    ticked, then a click, three steps of one box)."""
    kept: Act | None = None
    for act in [a for a in acts if a.role == "step"]:
        if (
            kept is not None
            and act.kind in ("check", "uncheck", "click")
            and _same_target(kept, act)
            and _same_row(kept.event.target, act.event.target)
            and not any(o.type in _SHOWED for o in kept.observed)
        ):
            if act.kind == "click":
                act.role = "superseded"
                continue
            kept.role = "superseded"
            act.observed = kept.observed + act.observed
        kept = act if act.kind in ("check", "uncheck") else None


def _same_row(one: ElementInfo | None, other: ElementInfo | None) -> bool:
    """Both out of any table's rows, or in the same row (a column's boxes are one per row)."""
    a = one.row if one is not None else None
    b = other.row if other is not None else None
    if a is None or b is None:
        return a is b
    return (a.table, a.index) == (b.table, b.index)


def _same_record(clicked: RowContext, filled: RowContext, column: str) -> bool:
    """The row a cell's editor was opened in and the row its value went into are one record.
    The click may be read before the edit and the fill after it (benchmark D04, 18.10: „Ilość
    po” 371 and „Netto różnica” 0,00 at the double click, 185 and -141,36 once typed): the
    cell typed and the cells the program counts from it differ, most of the others agree."""
    if clicked.cells == filled.cells:
        return True
    if clicked.cells.keys() != filled.cells.keys():
        return False
    others = [h for h in clicked.cells if h != column]
    agree = sum(clicked.cells[h] == filled.cells[h] for h in others)
    return agree * 2 > len(others)


_SUGGESTING = {"combobox", "searchbox", "textbox"}
_SUBMITTED_WITHIN_S = 0.5
"""Enter in a field sends its form by a click on the form's button the browser makes at once."""


def _merge_enter_with_its_click(acts: list[Act]) -> None:
    """Enter in a form's field and the click on its button that the browser makes for it are
    one act: the click, as for people who click the button themselves. Taken for two, the
    Enter was a step only some people take, and a rule was looked for in who was signed in
    (benchmark: style_rule_on_user)."""
    steps = [a for a in acts if a.role == "step"]
    for pressed, clicked in pairwise(steps):
        target = clicked.event.target
        if (
            pressed.kind == "press"
            and (pressed.event.value or "") == "Enter"
            and pressed.event.target is not None
            and clicked.kind == "click"
            and target is not None
            and target.role == "button"
            and clicked.event.t - pressed.event.t <= _SUBMITTED_WITHIN_S
            and clicked.event.state_before == pressed.event.state_before
        ):
            pressed.role = "superseded"
            clicked.observed = pressed.observed + clicked.observed


_CELL_EDIT_S = 5.0
"""A cell's editor is typed into this soon after the click that opened it."""


def _merge_cell_edit(acts: list[Act]) -> None:
    """A table's cell clicked, then typed into (a desktop table's cell editor: a text field
    with no name of its own) is one act: the cell of that column filled, in that row. The
    click only opened the editor, and the text it shows is the new value already (benchmark
    D04: the quantity after the correction)."""
    steps = [a for a in acts if a.role == "step"]
    for clicked, typed in pairwise(steps):
        cell, field = clicked.event.target, typed.event.target
        if (
            clicked.kind == "click"
            and cell is not None
            and cell.row is not None
            and cell.column
            and typed.kind == "fill"
            and field is not None
            and not (field.name or field.label)
            and typed.event.t - clicked.event.t <= _CELL_EDIT_S
        ):
            clicked.role = "superseded"
            target = cell.model_copy(
                update={
                    "tag": "java:table cell",
                    "role": "cell",
                    "name": None,
                    "text": None,
                    "label": None,
                }
            )
            # the screen before is the click's: the row as it was before the edit
            typed.event = typed.event.model_copy(
                update={"target": target, "state_before": clicked.event.state_before}
            )


def _merge_file_dialog(acts: list[Act]) -> None:
    """A click that only opened the file dialog (a "Wybierz plik" button over a hidden file
    field) is part of the upload: the robot puts the file in directly, and clicking would
    open a dialog nobody answers. A click that showed something first stays a step."""
    steps = [a for a in acts if a.role == "step"]
    for clicked, uploaded in pairwise(steps):
        quiet = not any(o.type in ("appeared", "navigated") for o in clicked.observed)
        if clicked.kind == "click" and uploaded.kind == "upload" and quiet:
            clicked.role = "superseded"


_NEXT = re.compile(r"^(?:następn|nastepn|next|\u203a|\u00bb|>|\u2192)", re.IGNORECASE)
_PREVIOUS = re.compile(r"^(?:poprzedn|previous|prev|\u2039|\u00ab|<|\u2190)", re.IGNORECASE)
_DATE_WORDS = re.compile(
    r"\b(?:dat|kalend|termin|dzie[nń]|calendar|date|day)|\U0001f4c5", re.IGNORECASE
)
_CALENDAR_MOVES = ("click", "select", "press")


def _said(info: ElementInfo) -> str:
    return info.name or info.title or info.text or ""


def calendar_ladder(info: ElementInfo | None, *, box: bool = False) -> list[dict[str, Any]]:
    """The ways to find a calendar's part again: not by a path through the page's elements
    when anything else is known; the calendar itself never by what it shows (its month)."""
    if info is None:
        return []
    every = [rung.model_dump(exclude_none=True) for rung in info.candidates]
    steady = [r for r in every if "nth-of-type" not in r.get("css", "")]
    if box:
        return [
            r
            for r in steady
            if "text" not in r
            and not read_month(r.get("name", ""))
            and not find_day(r.get("name", ""))
        ]
    return steady or every


def _arrows(seen: CalendarSeen) -> tuple[ElementInfo | None, ElementInfo | None]:
    """What moves the calendar a month on and a month back: by its words, else the two
    unnamed arrows of the calendar (the one on the left goes back)."""
    forward = next((c for c in seen.controls if _NEXT.match(_said(c))), None)
    back = next((c for c in seen.controls if _PREVIOUS.match(_said(c))), None)
    if forward is None and back is None:
        unnamed = [
            c for c in seen.controls if not _said(c) and c.bbox and c.role in ("button", "link")
        ]
        if len(unnamed) == 2:
            back, forward = sorted(unnamed, key=lambda c: c.bbox[0] if c.bbox else 0)
    return forward, back


def _month_over(seen: CalendarSeen) -> tuple[int, int, str] | None:
    """The month the calendar showed: the one month among its texts."""
    found: dict[tuple[int, int], tuple[int, int, str]] = {}
    for text in [*seen.texts, *(_said(c) for c in seen.controls)]:
        month = read_month(text)
        if month is not None:
            found.setdefault(month[:2], month)
    return next(iter(found.values())) if len(found) == 1 else None


def _day_picked(seen: CalendarSeen) -> tuple[date, str, str | None] | None:
    """The date of the day clicked, how the days are named and how the month over them is
    (when the days do not say it); None when the days around it are no month of a calendar:
    a month shown whole, at least 28 of its days (not a table of dates, nor a pager)."""
    if not 0 <= seen.index < len(seen.days):
        return None
    clicked = seen.days[seen.index]
    found = find_day(clicked)
    month = _month_over(seen)
    caption = None
    if found is not None and found[2] is not None:  # "24 grudnia 2026"
        pattern, dates = found[3], days_of(seen.days, found[3], None)
    elif found is not None and month is not None:  # "24 grudnia" under "Grudzień 2026"
        pattern, caption = found[3], month[2]
        dates = days_of(seen.days, pattern, month[:2])
    elif clicked.isdigit() and month is not None:  # "24" under "December 2026"
        pattern, caption = "{d}", month[2]
        dates = numbered_days(seen.days, month[0], month[1])
    else:
        return None
    day = dates[seen.index]
    months = Counter((d.year, d.month) for d in dates if d is not None)
    if day is None or not months or max(months.values()) < 28:
        return None
    return day, pattern, caption


def _in_calendar(act: Act, seen: CalendarSeen) -> bool:
    """Whether an act was done in the calendar: where it was on the screen (or, without
    where the calendar was, in its window or on an arrow)."""
    info = act.event.target
    box = seen.box.bbox if seen.box is not None else None
    spot = info.bbox if info is not None else None
    if act.kind not in _CALENDAR_MOVES or info is None:
        return False
    if box is None or spot is None:
        window = seen.box is not None and seen.box.role == "dialog" and seen.box.name
        return bool(window and info.dialog == window) or bool(
            _NEXT.match(_said(info)) or _PREVIOUS.match(_said(info))
        )
    x, y, width, height = box
    middle = (spot[0] + spot[2] / 2, spot[1] + spot[3] / 2)
    return x - 4 <= middle[0] <= x + width + 4 and y - 4 <= middle[1] <= y + height + 4


def _beside(one: ElementInfo, other: ElementInfo) -> bool:
    """Two elements side by side on a line (a field and the button opening its calendar)."""
    if one.bbox is None or other.bbox is None:
        return False
    (x1, y1, w1, h1), (x2, y2, w2, h2) = one.bbox, other.bbox
    overlap = min(y1 + h1, y2 + h2) - max(y1, y2) > 0
    return overlap and max(x1, x2) - min(x1 + w1, x2 + w2) <= 48


def _opens_calendar(act: Act, day: Act, seen: CalendarSeen) -> bool:
    """Whether the click before the calendar was used opened it: on the same screen, a field
    or what sits next to the field, or what says it is for a date."""
    target = act.event.target
    if act.kind != "click" or target is None:
        return False
    if act.event.url != day.event.url and not _program(day):
        return False  # a page's calendar opens on that page; a program's in a window of its own
    if target.role in ("textbox", "combobox", "searchbox"):
        return True
    words = " ".join(w for w in (target.name, target.title, target.label, target.text) if w)
    if _DATE_WORDS.search(words):
        return True
    return seen.field is not None and _beside(target, seen.field)


def _field_showing(trace: Trace, act: Act, day: date) -> str | None:
    """The name of the field that shows the day once it is clicked."""
    state = trace.state(act.event.state_after)
    if state is None:
        return None
    ways = {
        day.isoformat(), f"{day:%d.%m.%Y}", f"{day:%m/%d/%Y}", f"{day:%d/%m/%Y}",
        f"{day.day}.{day.month}.{day.year}", f"{day.month}/{day.day}/{day.year}",
    }  # fmt: skip
    for node in parse_aria(state.aria).walk():
        if node.role not in ("textbox", "combobox") or not node.name or not node.value:
            continue
        read = read_day(node.value)
        written = (re.search(rf"(?<![\d.]){re.escape(w)}(?!\d)", node.value) for w in ways)
        if (read is not None and read[0] == day) or any(written):
            return node.name
    return None


def _seen_from_screen(trace: Trace, act: Act) -> CalendarSeen | None:
    """For a recording made before the recorder wrote what is around a day: the calendar as
    the screen before the click shows it (its window, days named by their dates, its month
    and buttons). Days that are only numbers need the recorder: they are left as they are."""
    target = act.event.target
    if act.kind != "click" or target is None or not target.role or not target.name:
        return None
    state = trace.state(act.event.state_before) if read_day(target.name) else None
    if state is None:
        return None
    root = parse_aria(state.aria)
    window = root.find("dialog", target.dialog) if target.dialog else None
    if window is None:  # the smallest part of the screen holding a month of such days
        holders = [
            node
            for node in root.walk()
            if node is not root
            and len(node.find_all(target.role)) >= 28
            and node.find(target.role, target.name)
        ]
        window = holders[-1] if holders else None
    dated = sum(1 for node in root.find_all(target.role) if read_day(node.name or ""))
    if window is None and dated >= 28:
        window = root  # a desktop program's calendar is a window of its own: the whole screen
    days = [node.name or "" for node in window.find_all(target.role)] if window else []
    if window is None or target.name not in days:
        return None
    controls = []
    for node in window.walk():
        if node.role in ("button", "link") and node.name:
            tag = "button" if node.role == "button" else "a"
            control = ElementInfo(tag=tag, role=node.role, name=node.name, dialog=target.dialog)
            control.candidates = candidates_for(control)
            controls.append(control)
    box = None
    if target.dialog:
        box = ElementInfo(tag="div", role="dialog", name=target.dialog)
        box.candidates = candidates_for(box)
    texts = [node.text() for node in window.walk() if node.role == "text" and node.text()]
    return CalendarSeen(
        days=days, index=days.index(target.name), role=target.role, texts=texts,
        controls=controls, box=box,
    )  # fmt: skip


def _calendar_like(seen: CalendarSeen) -> bool:
    """Days that are only numbers under the names of several months: a calendar, though
    which month the day clicked is of cannot be read."""
    numbers = {n for n in seen.days if n.isdigit() and 1 <= int(n) <= 31}
    texts = [*seen.texts, *(_said(c) for c in seen.controls)]
    months = {month[:2] for month in map(read_month, texts) if month is not None}
    return len(numbers) >= 28 and len(months) >= 2


def _same_element(one: ElementInfo | None, other: ElementInfo | None) -> bool:
    return one is not None and other is not None and (one.css, one.name) == (other.css, other.name)


def _picked_before(act: Act | None, seen: CalendarSeen) -> bool:
    """Whether the act before was a day picked in this same calendar, still open (the first
    day of a range): there was nothing to open it again with."""
    if act is None or act.picked is None or not _in_calendar(act, seen):
        return False
    return seen.field is None or _same_element(act.picked.field_used, seen.field)


def _program(act: Act) -> bool:
    """Whether the act was done in a desktop program (a Java one: its screens are windows)."""
    return (act.event.url or "").startswith("java://")


def _typed_instead(trace: Trace, opener: Act, day: Act, label: str | None) -> TraceEvent | None:
    """A desktop program's calendar fills a field one can also type into: the date typed into
    that field is the step. The Java robot types it, and so do other people doing the same
    process (benchmark M1: „Obowiązuje od” typed by some, picked in the calendar by others,
    which made two ways of one value a decision nobody could explain)."""
    state = trace.state(day.event.state_after)
    if state is None or not label:
        return None
    shown = next(
        (
            n
            for n in parse_aria(state.aria).walk()
            if n.role == "textbox" and n.name == label and n.value
        ),
        None,
    )
    if shown is None or {"disabled", "readonly"} & set(shown.attrs):
        return None
    opened = opener.event.target
    info = ElementInfo(
        tag="java:text",
        role="textbox",
        name=label,
        dialog=opened.dialog if opened is not None else None,
    )
    info.candidates = candidates_for(info)
    return day.event.model_copy(
        update={
            "type": "fill",
            "target": info,
            "value": shown.value,
            "url": opener.event.url,
            "state_before": opener.event.state_before,
        }
    )


def _program_pick(trace: Trace, steps: list[Act], index: int) -> bool:
    """A day clicked in a desktop program's calendar whose screen the recording did not read
    (a program's window told late: benchmark M1 r2, „Kalendarz” read as the main window). The
    day's name says the date („1 listopada 2026”), the click that opened the calendar names
    its field („Wybierz datę: Obowiązuje od”): the date typed into that field is the step, as
    when the calendar was read. Returns whether the acts were made one."""
    day = steps[index]
    target = day.event.target
    if day.kind != "click" or target is None or not target.dialog:
        return False
    read = read_day(target.name or "")
    if read is None:
        return False
    start = index
    while start > 0 and steps[start - 1].kind == "click":
        moved = steps[start - 1].event.target
        if moved is None or moved.dialog != target.dialog:
            break
        start -= 1  # a month moved in the calendar
    if start == 0:
        return False
    opener = steps[start - 1]
    opened = opener.event.target
    if opener.kind != "click" or opened is None or opened.dialog == target.dialog:
        return False
    said = opened.name or ""
    if ":" not in said or not _DATE_WORDS.search(said):
        return False
    label = said.rsplit(":", 1)[-1].strip()
    shown = _shown_after(trace, steps[index + 1 :], label, read[0]) or read[0].isoformat()
    info = ElementInfo(tag="java:text", role="textbox", name=label, dialog=opened.dialog)
    info.candidates = candidates_for(info)
    day.event = day.event.model_copy(
        update={
            "type": "fill",
            "target": info,
            "value": shown,
            "url": opener.event.url,
            "state_before": opener.event.state_before,
        }
    )
    for done in steps[start - 1 : index]:
        done.role = "superseded"
    day.observed = [o for done in steps[start - 1 : index] for o in done.observed] + day.observed
    return True


def _shown_after(trace: Trace, later: list[Act], label: str, day: date) -> str | None:
    """The field's text once the day was picked, as a later screen shows it (01-LIS-2026)."""
    for act in later[:4]:
        for state_id in (act.event.state_before, act.event.state_after):
            state = trace.state(state_id)
            if state is None:
                continue
            for node in parse_aria(state.aria).walk():
                if node.role == "textbox" and node.name == label and node.value:
                    read = read_day(node.value)
                    if read is not None and read[0] == day:
                        return node.value
    return None


def _merge_calendar(trace: Trace, acts: list[Act]) -> None:
    """A day picked in a calendar is one act: picking that date. The person opens the
    calendar (with a click, or by going into its field), moves it month by month and clicks
    the day; kept as clicks, the model would pick the recorded day for every record
    (benchmark: calendar_constant). The recorder wrote down what was around the day."""
    steps = [a for a in acts if a.role == "step"]
    for index, act in enumerate(steps):
        target = act.event.target
        seen = target.calendar if act.kind == "click" and target is not None else None
        seen = seen or _seen_from_screen(trace, act)
        picked = _day_picked(seen) if seen is not None else None
        if seen is not None and picked is None and _calendar_like(seen):
            act.calendar_unread = True
        if seen is None and _program(act) and _program_pick(trace, steps, index):
            continue
        if seen is None or picked is None:
            continue
        start = index
        while start > 0 and steps[start - 1].role == "step" and steps[start - 1].picked is None:
            if not _in_calendar(steps[start - 1], seen):
                break
            start -= 1
        before = steps[start - 1] if start > 0 else None
        opener = before if before is not None and _opens_calendar(before, act, seen) else None
        if _picked_before(before, seen) and calendar_ladder(seen.box, box=True):
            assert seen.box is not None  # the end of a range, in the calendar still open
            what, opens, opener = seen.box, False, None
        elif opener is not None and opener.event.target is not None:
            what, opens = opener.event.target, True
            start -= 1
        elif seen.field is not None:  # going into the field opened it (no step of its own)
            what, opens = seen.field, True
        elif calendar_ladder(seen.box, box=True):  # always shown
            assert seen.box is not None
            what, opens = seen.box, False
        else:
            continue
        label = _field_showing(trace, act, picked[0])
        if label is None and opener is None and seen.field is not None:
            label = seen.field.label or seen.field.name or seen.field.placeholder
        if label is None and opener is not None:
            said = _said(what)
            label = said.rsplit(":", 1)[-1].strip() if ":" in said else what.label or said
        if label is None and not opens:  # a calendar always shown: what it is called
            label = what.name or what.label
        label = _HELP_MARK.sub("", label or "") or label  # "Validity Period?": the field
        typed = (
            _typed_instead(trace, opener, act, label)
            if opener is not None and _program(act)
            else None
        )
        if typed is not None:
            act.event = typed
            for done in steps[start:index]:
                done.role = "superseded"
            act.observed = [o for done in steps[start:index] for o in done.observed] + act.observed
            continue
        forward, back = _arrows(seen)
        days = {"role": seen.role} if seen.role else {"css": seen.css or "*"}
        earlier = steps[start:index]
        act.picked = DatePick(
            picked[0], picked[1], days, picked[2], what, opens, label or "Data",
            box=seen.box, next=forward, previous=back,
            seqs=[a.seq for a in earlier] + [act.seq], field_used=seen.field,
        )  # fmt: skip
        for done in earlier:
            done.role = "superseded"
        act.observed = [o for done in earlier for o in done.observed] + act.observed


def _merge_choices(acts: list[Act]) -> None:
    """'Type 48212-B, pick “[48212-B] Shelf-ready tray”' is one act: choose 48212-B."""
    steps = [a for a in acts if a.role == "step"]
    for typed, picked in pairwise(steps):
        field_target, option = typed.event.target, picked.event.target
        value = (typed.event.value or "").strip().lower()
        if (
            typed.kind == "fill"
            and picked.kind == "click"
            and field_target is not None
            and field_target.role in _SUGGESTING
            and option is not None
            and option.role == "option"
            and value
            and value in (option.name or option.text or "").lower()
        ):
            typed.chosen = picked.event
            typed.observed += picked.observed
            picked.role = "superseded"


_DONE_STATUS = re.compile(
    r"^\s*(?:zapisano|zapisan[aey]|dodano|dodan[aey]|utworzono|zaksięgowano|wysłano|"
    r"przeliczono|zatwierdzono|saved|added|created|posted|sent|done)\b",
    re.IGNORECASE,
)
"""A status saying the action was done: a step's result, never a refusal."""

_REFUSED_STATUS = re.compile(
    r"^\s*(?:brak tabeli z dnia\b|no (?:table|rates?) (?:for|on)\b)", re.IGNORECASE
)
"""Known read refusals that explicitly say no result was available."""


def _status_words(text: str) -> str:
    """A status without its values („Brak tabeli z dnia #-#-#”): the same message again."""
    return re.sub(r"\d+", "#", " ".join(text.split())).casefold()


def _refused_by_status(act: Act, again: Act) -> str | None:
    """The status an action showed when it was refused without a word of alarm (no table for a
    day without quotations): it wrote nothing, and the same action, done again with another
    value, does not show that status. None when it is no such refusal."""
    if act.event.sent:
        return None  # it wrote something: a result of its own (a line added), not a refusal
    statuses = [o.target.text for o in act.appeared("status") if o.target and o.target.text]
    if (
        not statuses
        or any(_DONE_STATUS.search(s) for s in statuses)
        or not _REFUSED_STATUS.search(statuses[-1])
    ):
        return None
    later = {
        _status_words(o.target.text) for o in again.appeared("status") if o.target and o.target.text
    }
    return statuses[-1] if _status_words(statuses[-1]) not in later else None


def _merge_attempts(acts: list[Act]) -> None:
    """Fold 'rejected, corrected, repeated' into the repeated action: rejected with an alert,
    or with a status after which the person typed another value and tried again (a day
    without a table of rates, then the day before it)."""
    changed = True
    while changed:
        changed = False
        steps = [a for a in acts if a.role == "step"]
        for i, act in enumerate(steps):
            alerts = act.appeared("alert")
            if act.kind not in ("click", "press") or not (alerts or act.appeared("status")):
                continue
            j = next(
                (
                    k
                    for k in range(i + 1, len(steps))
                    if steps[k].kind not in _ENTRY or _same_target(steps[k], act)
                ),
                None,
            )
            if j is None or not _same_target(steps[j], act) or steps[j].kind != act.kind:
                continue
            entered_again = {s.field_name for s in steps[i + 1 : j]}
            before: list[Act] = []
            for k in range(i - 1, -1, -1):
                if steps[k].kind not in _ENTRY:
                    break
                before.append(steps[k])
            replaced = [s for s in before if s.field_name in entered_again]
            if alerts:
                message = alerts[-1].target.text if alerts[-1].target else None
                role = "alert"
            else:
                changed_value = any(
                    s.event.value != t.event.value
                    for s in replaced
                    for t in steps[i + 1 : j]
                    if t.field_name == s.field_name
                )
                message = _refused_by_status(act, steps[j]) if changed_value else None
                role = "status"
                if message is None:
                    continue
            values = {s.field_name or "?": s.event.value or "" for s in replaced}
            seqs = [s.seq for s in replaced] + [act.seq]
            for superseded in [*replaced, act]:
                superseded.role = "superseded"
            steps[j].attempts.append(Attempt(message or "", values, seqs, role))
            steps[j].attempts.extend(act.attempts)
            changed = True
            break


def _clicked_in_closed_question(trace: Trace) -> None:
    """A desktop program's question closes as its button is clicked („Tak” to „Zapisać
    wniosek?” after „Zapisz”); the bridge may then tell the click in the window under it, the
    only one left open. The screen read just before the click is that question, with the one
    button of that name: the click was in it, as the recorder tells it when it is quicker (its
    step is „W oknie „SRK - pytanie” kliknij „Tak””, and the yes saves what „Zapisz” asked)."""
    if trace.header.program is None:
        return
    for event in trace.events:
        target = event.target
        if event.type != "click" or target is None or target.dialog or not target.name:
            continue
        before = trace.states.get(event.state_before or "")
        if before is None or before.window <= event.window or before.url == event.url:
            continue
        lines = before.aria.splitlines()
        opened = re.fullmatch(r'- dialog "(.+)"', lines[0].strip()) if lines else None
        if opened is None:
            continue
        button = f'- {target.role} "{target.name}"'
        if sum(line.strip() == button for line in lines) != 1:
            continue
        event.url, event.title, event.window = before.url, before.title, before.window
        target.dialog = opened.group(1)


_ITEM_FIELD = re.compile(r"(?P<words>[^:]+):\s+(?P<item>\S*\d\S*)")
"""A field named for an item: its words, a colon, the item's code („Przyjęto: 37241-E”)."""


def _item_fields(trace: Trace, acts: list[Act]) -> None:
    """A field named for the item it is filled for, which the screen names elsewhere too
    („37241-E: przyjechało 20 szt.”): the field whose name starts with its words, for every
    record (``ANY_WORD`` for the code; ``Act.item`` keeps the code of this recording)."""
    for act in acts:
        target = act.event.target
        if act.kind not in ("fill", "select") or target is None or trace.header.program:
            continue
        found = _ITEM_FIELD.fullmatch((target.label or target.name or "").strip())
        state = trace.state(act.event.state_before)
        if found is None or state is None or len(found.group("item")) < 4:
            continue
        item = found.group("item")
        token = re.compile(r"(?<![\w-])" + re.escape(item) + r"(?![\w-])")
        texts = [
            text
            for node in parse_aria(state.aria).walk()
            for text in (node.name, node.value)
            if text and token.search(text) and not _ITEM_FIELD.fullmatch(text.strip())
        ]
        if not texts:
            continue  # the screen does not name the item: a field of its own name
        pattern = f"{found.group('words').strip()}: {ANY_WORD}"
        act.item = item
        target.label = pattern if target.label else None
        target.name = pattern if target.name else None
        target.css = None  # its place is the item's: the next record's item is elsewhere
        target.candidates = candidates_for(target)


def _clicked_in_closed_window(trace: Trace) -> None:
    """A window that closes as its button is clicked („Open” in Java's file chooser, benchmark
    M3), told by the bridge in no window at all (the program's own address, no window's name)
    and with the screen under it read: the click was in the window of the action before it, a
    window over that screen, when that screen has no such button."""
    if trace.header.program is None:
        return
    actions = [e for e in trace.events if e.is_action]
    for before, event in pairwise(actions):
        target, earlier = event.target, before.target
        if event.type != "click" or target is None or target.dialog or not target.name:
            continue
        if _path(event.url).strip("/") or earlier is None or not earlier.dialog:
            continue
        if before.window <= event.window:
            continue
        screen = trace.states.get(event.state_before or "")
        button = f'- {target.role} "{target.name}"'
        if screen is not None and any(line.strip() == button for line in screen.aria.splitlines()):
            continue  # the screen under it has the button: it may have been clicked there
        event.url, event.title, event.window = before.url, before.title, before.window
        target.dialog = earlier.dialog


def normalize(trace: Trace) -> Normalized:
    _clicked_in_closed_question(trace)
    _clicked_in_closed_window(trace)
    acts = group_acts(trace)
    _item_fields(trace, acts)
    after_login = _mark_login(trace, acts)
    _mark_interrupts(trace, acts)
    _merge_calendar(trace, acts)  # a day clicked shows nothing new, yet it is no stray click
    _mark_noise(acts)
    _merge_box_toggles(acts)
    if trace.header.program is None:  # only a browser clicks the form's button for an Enter
        _merge_enter_with_its_click(acts)
    else:  # a desktop table's cell edited in its editor
        _merge_cell_edit(acts)
    _merge_file_dialog(acts)
    _merge_choices(acts)
    _merge_attempts(acts)
    return Normalized(trace=trace, acts=acts, start_url=after_login or trace.header.start_url)
