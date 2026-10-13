"""Recording format ("trace"), version 0.1.

A trace is a JSON Lines file: a header, then events and screen states in the order they
were observed, then an end record. Screenshots are separate files next to it.

Traces keep what was observed, not what we think it meant: they are the raw material
for mapping (M2) and rule induction (M4). Secrets (password fields) are never stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from maptelo import formerly
from maptelo.model.schema import Locator

TRACE_FORMAT: Literal["maptelo-trace/0.1"] = "maptelo-trace/0.1"

ActionType = Literal[
    "navigate", "click", "fill", "select", "check", "uncheck", "press", "upload"
]  # fmt: skip
ObservationType = Literal["appeared", "navigated", "downloaded", "dialog"]
ACTION_TYPES: tuple[str, ...] = (
    "navigate", "click", "fill", "select", "check", "uncheck", "press", "upload"
)  # fmt: skip


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RowContext(_Record):
    """The table row an element sits in: lets a rule say 'the row where Status is Active'."""

    table: str | None = None
    cells: dict[str, str] = Field(default_factory=dict)
    index: int | None = None


class ElementInfo(_Record):
    """What the recorder saw of an element at the moment of the action."""

    tag: str
    type: str | None = None
    autocomplete: str | None = Field(
        default=None, description="What the field says it holds (one-time-code, email...)."
    )
    role: str | None = None
    name: str | None = Field(default=None, description="Accessible name (approximation).")
    label: str | None = None
    field: str | None = Field(default=None, description="The name a form sends the value under.")
    submits: str | None = Field(
        default=None, description="For a button that sends a form: a field only that form sends."
    )
    placeholder: str | None = None
    testid: str | None = None
    action: str | None = Field(
        default=None,
        description='For a button: the name of what it does (<button name="action_confirm">).',
    )
    text: str | None = None
    title: str | None = Field(
        default=None,
        description="What its tooltip says when no text names it (an icon: its title, or the "
        "title of the icon inside it).",
    )
    id: str | None = None
    css: str | None = None
    classes: str | None = Field(
        default=None,
        description="A CSS selector of its own class names that found only it when recorded "
        "(div.o_datetime_picker); written for the elements of a calendar.",
    )
    bbox: tuple[int, int, int, int] | None = None
    row: RowContext | None = None
    column: str | None = Field(default=None, description="Header of the table column it is in.")
    dialog: str | None = Field(default=None, description="Name of the enclosing dialog.")
    calendar: CalendarSeen | None = Field(
        default=None, description="For a click on a day of a calendar: what was around it."
    )
    candidates: list[Locator] = Field(
        default_factory=list, description="Locator ladder, most robust first."
    )

    def describe(self) -> str:
        if self.role and self.name:
            return f'{self.role} "{self.name}"'
        if self.label:
            return f'field "{self.label}"'
        if self.role and self.column:
            return f'{self.role} in column "{self.column}"'
        if self.text:
            return f'{self.tag} "{self.text}"'
        return self.css or self.tag


class CalendarSeen(_Record):
    """What was around a day clicked in a calendar, as the recorder saw it: whether it was a
    calendar, and which day, is decided when the recording is mapped."""

    days: list[str] = Field(description="The names of the calendar's days, in the order shown.")
    index: int = Field(description="Where the clicked day is among them.")
    role: str | None = Field(default=None, description="The role the days share.")
    css: str | None = Field(
        default=None, description="Without a role: the tag and class the days share (span.day)."
    )
    texts: list[str] = Field(
        default_factory=list, description="Short texts around the days: the month shown..."
    )
    controls: list[ElementInfo] = Field(
        default_factory=list, description="What can be clicked around the days (its arrows)."
    )
    box: ElementInfo | None = Field(
        default=None, description="The element holding the days, the month and the arrows."
    )
    field: ElementInfo | None = Field(
        default=None, description="The text field used last before: the calendar may be its."
    )


ElementInfo.model_rebuild()


class DataRef(_Record):
    """The table the person took values from during the recording (a copy is kept)."""

    file: str = Field(description="Path of the copy, relative to the recording folder.")
    sheet: str | None = Field(default=None, description="Sheet of a workbook, if given.")


class TraceHeader(_Record):
    kind: Literal["header"] = "header"
    format: Literal["maptelo-trace/0.1"] = TRACE_FORMAT
    recording_id: str
    process: str | None = None
    title: str | None = Field(
        default=None,
        description="The process as the person named it („Zmiana cen klientów”); ``process`` is "
        "its folder name.",
    )
    note: str | None = None
    source: Literal["maptelo-recorder", "chrome-devtools-recorder"] = "maptelo-recorder"
    started_at: datetime
    start_url: str
    browser: str | None = None
    viewport: tuple[int, int] | None = None
    timezone: str | None = Field(default=None, description="The browser's time zone (IANA).")
    locale: str | None = Field(default=None, description="The browser's language, e.g. en-US.")
    data: DataRef | None = Field(
        default=None, description="The table the values came from (M7: Excel or CSV)."
    )
    private: bool = Field(
        default=False,
        description="Recorded as private: screenshots cover what was typed and table contents.",
    )
    program: str | None = Field(
        default=None,
        description="A Java program recorded through the Java Access Bridge: its name as its "
        "main window shows it ('SRK', 'Oracle Applications').",
    )

    @field_validator("format", "source", mode="before")
    @classmethod
    def _old_name(cls, value: object) -> object:
        """Recordings made before the rename are read as today's (formerly.py)."""
        return formerly.TRACE_NAMES.get(value, value) if isinstance(value, str) else value


class DialogSeen(_Record):
    """A dialog of the browser itself (not of the page): ``alert``, ``confirm`` or ``prompt``,
    what it asked and how the person answered. Old programs ask so before saving („Zapisać
    zmiany?”, „Podaj powód zmiany”)."""

    kind: Literal["alert", "confirm", "prompt"]
    message: str = ""
    accepted: bool = Field(default=True, description="OK (True) or Cancel (False).")
    value: str | None = Field(default=None, description="What was typed into a prompt.")


class TraceEvent(_Record):
    kind: Literal["event"] = "event"
    seq: int = Field(ge=1)
    t: float = Field(ge=0, description="Seconds since the recording started.")
    type: ActionType | ObservationType
    url: str | None = None
    title: str | None = None
    target: ElementInfo | None = None
    value: str | None = None
    option_label: str | None = Field(default=None, description="Visible text of a chosen option.")
    secret: bool = Field(default=False, description="The value was withheld (password).")
    files: list[str] = Field(
        default_factory=list,
        description="Names of the files chosen (upload) or saved (downloaded): never their "
        "content or their folder.",
    )
    sent: list[str] = Field(
        default_factory=list,
        description="Requests this action set off that send data to the application: method "
        "and path, never what was sent (``POST /orders/12/invoice``).",
    )
    dialog: DialogSeen | None = Field(default=None, description="For a 'dialog' observation.")
    window: int = Field(
        default=0,
        ge=0,
        description="The window it happened in: 0 the first, 1 the first one opened after it "
        "(a chooser, an approval, a print preview), and so on.",
    )
    state_before: str | None = None
    state_after: str | None = None

    @property
    def is_action(self) -> bool:
        return self.type in ACTION_TYPES


class TraceState(_Record):
    """The screen after things settled: accessibility snapshot (+ screenshot file)."""

    kind: Literal["state"] = "state"
    id: str
    t: float = Field(ge=0)
    url: str
    title: str | None = None
    aria: str
    screenshot: str | None = None
    screenshot_t: float | None = Field(
        default=None,
        ge=0,
        description="When the picture was taken, when it may show more than the state: fields "
        "typed into after ``t`` show their later text in it (the snapshot shows what they held "
        "at ``t``).",
    )
    window: int = Field(default=0, ge=0, description="The window this screen is of.")
    origin: tuple[int, int] | None = Field(
        default=None,
        description="Where the picture's top left corner was on the screen, when the places of "
        "elements are the screen's (a Java window's picture is the window alone): marks on it "
        "are drawn this far back.",
    )
    scale: float | None = Field(
        default=None,
        gt=0,
        description="The picture's pixels per pixel of the elements' places, when the two "
        "differ: a display scaled to 125 % shows a Java program that knows it in the screen's "
        "pixels while the picture is in the scaled ones. ``origin`` is then in the elements' "
        "places too.",
    )


class TraceEnd(_Record):
    kind: Literal["end"] = "end"
    t: float = Field(ge=0)
    ended_at: datetime
    reason: Literal["closed", "stopped", "timeout", "imported"] = "stopped"
    events: int = Field(ge=0)
    states: int = Field(ge=0)


TraceRecord = Annotated[
    TraceHeader | TraceEvent | TraceState | TraceEnd, Field(discriminator="kind")
]


@dataclass
class Trace:
    header: TraceHeader
    events: list[TraceEvent] = field(default_factory=list)
    states: dict[str, TraceState] = field(default_factory=dict)
    end: TraceEnd | None = None
    path: Path | None = None

    def actions(self) -> list[TraceEvent]:
        return [e for e in self.events if e.is_action]

    def state(self, state_id: str | None) -> TraceState | None:
        return self.states.get(state_id) if state_id else None
