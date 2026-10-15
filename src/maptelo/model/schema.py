"""Process model, format version 0.1.

The model is the product: recordings are raw material and executors (Playwright, API,
agent, human) are interchangeable. YAML is the source of truth; this module defines the
typed schema. Cross-references are checked in ``integrity.py``, soft issues in ``lint.py``.

Value references: a string that is exactly ``$inputs.name`` or ``$vars.name`` is replaced
by that (typed) value. Inside longer strings use ``{inputs.name}`` placeholders.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

FORMAT_VERSION = "0.1"

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]
"""snake_case id of a step, input, state, effect, exception, interrupt or variable."""

Scalar = bool | int | float | date | str
"""A literal value, or a ``$inputs.name`` / ``$vars.name`` reference when it is a string."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _exactly_one(obj: BaseModel, names: tuple[str, ...], what: str) -> str:
    chosen = [n for n in names if getattr(obj, n) is not None]
    if len(chosen) != 1:
        shown = ", ".join(n.rstrip("_") for n in names)  # attribute all_ is key 'all' in YAML
        got = ", ".join(n.rstrip("_") for n in chosen) or "none"
        raise ValueError(f"{what} needs exactly one of: {shown} (got: {got})")
    return chosen[0]


def _version_as_text(value: Any) -> Any:
    # An unquoted `schema_version: 0.1` arrives from YAML as a float.
    return str(value) if isinstance(value, int | float) and not isinstance(value, bool) else value


# --- Locating elements ---------------------------------------------------------------

LOCATOR_STRATEGIES = (
    "role", "label", "field", "submits", "placeholder", "beside", "testid", "action", "text",
    "css",
)  # fmt: skip


class Locator(_Model):
    """One rung of a target ladder. Exactly one strategy is set."""

    role: str | None = Field(default=None, description="ARIA role, e.g. button, textbox.")
    name: str | None = Field(default=None, description="Accessible name; only with 'role'.")
    column: str | None = Field(
        default=None,
        description="Header of the table column the element is in (for a definition: its "
        "term, as in 'Numer rachunku: PL61...'); only with 'role'.",
    )
    label: str | None = None
    field: str | None = Field(
        default=None,
        description="The name a form sends the value under (name attribute), on the control "
        "or on the one element around a lone control; it rarely changes when the words do.",
    )
    submits: str | None = Field(
        default=None,
        description="The button that sends the form holding the field of this name (its only "
        "submit button); an update renames the button more often than what it sends.",
    )
    placeholder: str | None = None
    beside: str | None = Field(
        default=None,
        description="A field nothing names (no label of its own), by the words beside it in "
        "its own row or box („Genre:”), as a person reads which field it is.",
    )
    testid: str | None = None
    action: str | None = Field(
        default=None,
        description="A button by the name of what it does in the application "
        '(<button name="action_confirm">, as Odoo writes them): it stays when the words '
        "change or are translated.",
    )
    text: str | None = None
    css: str | None = None

    @model_validator(mode="after")
    def _one_strategy(self) -> Self:
        _exactly_one(self, LOCATOR_STRATEGIES, "a locator")
        if self.name is not None and self.role is None:
            raise ValueError("'name' is only valid together with 'role'")
        if self.column is not None and self.role is None:
            raise ValueError("'column' is only valid together with 'role'")
        return self

    @property
    def strategy(self) -> str:
        return next(s for s in LOCATOR_STRATEGIES if getattr(self, s) is not None)

    def describe(self) -> str:
        if self.role is not None:
            text = f"role={self.role}" + (f' name="{self.name}"' if self.name else "")
            return text + (f' column="{self.column}"' if self.column else "")
        return f'{self.strategy}="{getattr(self, self.strategy)}"'


def _one_or_many(value: Any) -> Any:
    return [value] if isinstance(value, dict) else value


Target = Annotated[list[Locator], BeforeValidator(_one_or_many), Field(min_length=1)]
"""Locators tried in order (first unambiguous match wins). A single mapping is one rung."""


class RowScope(_Model):
    """Rows of a table, filtered by column values (``null`` matches an empty cell)."""

    table: Target
    where: dict[str, Scalar | None] = Field(default_factory=dict)


class WithinRow(RowScope):
    """Restricts a step's target to one table row. 'only' refuses to guess between rows;
    'newest' and 'oldest' take the row with the latest or earliest date in the column ``by``
    („the most recent pending order”); 'each' does the step in every row that fits, none being
    fine (a box unticked in each row with an error)."""

    pick: Literal["only", "first", "last", "each", "newest", "oldest"] = "only"
    by: str | None = Field(
        default=None,
        description="For 'newest'/'oldest': the column whose dates order the rows.",
    )
    where_not: dict[str, Scalar | None] = Field(
        default_factory=dict,
        description="Columns the row must not hold the value in (null: must not be empty: "
        "the rows with an error, benchmark M3).",
    )

    @model_validator(mode="after")
    def _ordered_by(self) -> Self:
        if (self.pick in ("newest", "oldest")) != (self.by is not None):
            raise ValueError("'newest'/'oldest' need 'by' (a date column), and only they take it")
        return self


# --- Conditions ----------------------------------------------------------------------


class CountCheck(_Model):
    eq: int | None = Field(default=None, ge=0)
    gt: int | None = Field(default=None, ge=0)
    gte: int | None = Field(default=None, ge=0)
    lt: int | None = Field(default=None, ge=0)
    lte: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _one_comparator(self) -> Self:
        _exactly_one(self, ("eq", "gt", "gte", "lt", "lte"), "a count check")
        return self


class RowsCheck(RowScope):
    count: CountCheck


class FieldCheck(_Model):
    """Value of a form field, found by label or by a target ladder."""

    label: str | None = None
    target: Target | None = None
    equals: Scalar | None = None
    contains: str | None = None
    empty: bool | None = None
    gt: float | None = Field(default=None, description="The number it shows is greater.")
    gte: float | None = Field(default=None, description="The number it shows is at least this.")
    lt: float | None = Field(default=None, description="The number it shows is smaller.")
    lte: float | None = Field(default=None, description="The number it shows is at most this.")

    @model_validator(mode="after")
    def _shape(self) -> Self:
        _exactly_one(self, ("label", "target"), "a field check")
        _one_test(self, "a field check")
        return self


class ValueCheck(_Model):
    """A value of the record (or one read earlier on a screen) compared: a decision made from
    the data, as people make it from their sheet ("Faktura zbiorcza: tak" ticks the box)."""

    of: str = Field(description="The value: '$inputs.x' (the record) or '$vars.x' (read).")
    equals: Scalar | None = Field(default=None, description="Compared as text, any case.")
    one_of: list[Scalar] | None = Field(default=None, min_length=1)
    empty: bool | None = None
    gt: float | None = Field(default=None, description="The number it shows is greater.")
    gte: float | None = Field(default=None, description="The number it shows is at least this.")
    lt: float | None = Field(default=None, description="The number it shows is smaller.")
    lte: float | None = Field(default=None, description="The number it shows is at most this.")

    @model_validator(mode="after")
    def _shape(self) -> Self:
        _one_test(self, "a value check", ("equals", "one_of", "empty"))
        if not re.fullmatch(r"\$(inputs|vars)\.[a-z][a-z0-9_]*", self.of):
            raise ValueError("'of' is '$inputs.<name>' or '$vars.<name>'")
        return self


_BOUNDS = ("gt", "gte", "lt", "lte")


def _one_test(
    check: object, what: str, tests: tuple[str, ...] = ("equals", "contains", "empty")
) -> None:
    """One test: equals, contains, empty... or a comparison of the number (a lower and an upper
    bound may go together: from 1 to 7 days)."""
    set_tests = [name for name in tests if getattr(check, name) is not None]
    bounds = [name for name in _BOUNDS if getattr(check, name) is not None]
    if bounds and not set_tests:
        if ("gt" in bounds and "gte" in bounds) or ("lt" in bounds and "lte" in bounds):
            raise ValueError(f"{what}: one lower and one upper bound at most")
        return
    if len(set_tests) != 1 or bounds:
        names = ", ".join([*tests, *_BOUNDS])
        raise ValueError(f"{what}: exactly one of {names} (or a lower and an upper bound)")


PREDICATE_KINDS = (
    "visible", "hidden", "url", "state", "field", "value", "rows", "all_", "any_", "not_",
)  # fmt: skip


class Predicate(_Model):
    """An observable condition. Exactly one kind is set; all/any/not combine others."""

    visible: Locator | None = None
    hidden: Locator | None = None
    url: str | None = Field(
        default=None,
        description="Glob matched against the page path; a #part (key=glob&...) must match too.",
    )
    state: Identifier | None = None
    field: FieldCheck | None = None
    value: ValueCheck | None = None
    rows: RowsCheck | None = None
    all_: list[Predicate] | None = Field(default=None, alias="all", min_length=1)
    any_: list[Predicate] | None = Field(default=None, alias="any", min_length=1)
    not_: Predicate | None = Field(default=None, alias="not")

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        _exactly_one(self, PREDICATE_KINDS, "a condition")
        return self

    def walk(self) -> list[Predicate]:
        """This predicate and every nested one."""
        nested: list[Predicate] = [self]
        for child in (self.all_ or []) + (self.any_ or []) + ([self.not_] if self.not_ else []):
            nested.extend(child.walk())
        return nested


# --- Steps ---------------------------------------------------------------------------


class Action(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    SELECT_OPTION = "select_option"
    CHECK = "check"
    UNCHECK = "uncheck"
    PRESS = "press"
    READ = "read"
    WAIT = "wait"
    CHOOSE = "choose"
    """Type the value into a field with suggestions and pick the first one containing it."""
    UPLOAD = "upload"
    """Put a file into a file field: its path from the data, or a file downloaded earlier."""
    DOWNLOAD = "download"
    """Click what gives a file and keep the file (``save_as``: for a later upload)."""
    PICK_DATE = "pick_date"
    """Open a calendar (the target) and click the day of the value, moving between months."""


ELEMENT_ACTIONS = frozenset(
    {
        Action.CLICK,
        Action.FILL,
        Action.SELECT_OPTION,
        Action.CHECK,
        Action.UNCHECK,
        Action.READ,
        Action.CHOOSE,
        Action.UPLOAD,
        Action.DOWNLOAD,
        Action.PICK_DATE,
    }
)
VALUE_ACTIONS = frozenset(
    {
        Action.NAVIGATE,
        Action.FILL,
        Action.SELECT_OPTION,
        Action.PRESS,
        Action.CHOOSE,
        Action.UPLOAD,
        Action.PICK_DATE,
    }
)
READ_ONLY_ACTIONS = frozenset({Action.NAVIGATE, Action.READ, Action.WAIT, Action.DOWNLOAD})


class RiskClass(StrEnum):
    READ = "read"
    DRAFT = "draft"
    COMMIT = "commit"
    IRREVERSIBLE = "irreversible"


class Executor(StrEnum):
    DETERMINISTIC = "deterministic"
    AGENT = "agent"
    HUMAN = "human"


def _check_action_args(
    action: Action, target: object, value: object, *, words: bool = False
) -> None:
    """``words``: a 'read' finds its value by the words before it, not by an element."""
    if action in ELEMENT_ACTIONS and target is None and not (words and action is Action.READ):
        raise ValueError(f"action '{action}' requires 'target'")
    if action in (Action.NAVIGATE, Action.WAIT) and target is not None:
        raise ValueError(f"action '{action}' does not take 'target'")
    if action in VALUE_ACTIONS and value is None:
        raise ValueError(f"action '{action}' requires 'value'")
    if action not in VALUE_ACTIONS and value is not None:
        raise ValueError(f"action '{action}' does not take 'value'")


class OutcomeHandler(_Model):
    raise_: Identifier | None = Field(default=None, alias="raise")
    goto: Identifier | None = None
    continue_: Literal[True] | None = Field(default=None, alias="continue")

    @model_validator(mode="after")
    def _one_handler(self) -> Self:
        _exactly_one(self, ("raise_", "goto", "continue_"), "an outcome handler")
        return self


class Calendar(_Model):
    """How a calendar shows its days and months and how it moves, for 'pick_date'."""

    day: str = Field(
        description="How a day is named: '{d} {month} {yyyy}' for '24 listopada 2026', '{d}' "
        "for days that are only numbers (fields of maptelo.dates)."
    )
    days: Locator = Field(
        default_factory=lambda: Locator(role="gridcell"),
        description="What a day of the calendar is: a role (gridcell, button) or a CSS selector, "
        "without a name.",
    )
    month: str | None = Field(
        default=None,
        description="How the month shown over the days is named ('{Month_en} {yyyy}' for "
        "'October 2026'), when the days do not say their month and year.",
    )
    box: Target | None = Field(
        default=None, description="The calendar: where its days, its month and its arrows are."
    )
    next: Target | None = Field(default=None, description="What moves it to the next month.")
    previous: Target | None = Field(default=None, description="What moves it a month back.")
    opens: bool = Field(
        default=True,
        description="The step's target opens the calendar (it is clicked first); false for a "
        "calendar always shown, the step's target being the calendar itself.",
    )

    @model_validator(mode="after")
    def _days_and_month(self) -> Self:
        if self.days.strategy not in ("role", "css") or self.days.name is not None:
            raise ValueError("'days' is a role or a CSS selector, without a name")
        if "{yyyy}" not in self.day and self.month is None:
            raise ValueError("'month' is required when the days do not say their year")
        return self


class Evidence(_Model):
    """Where a step or rule came from: recordings that support it and who confirmed it."""

    traces: list[str] = Field(default_factory=list)
    confirmed_by: str | None = None
    note: str | None = None


class DialogAnswer(_Model):
    """How a dialog of the browser itself, brought up by the step, is answered: as the
    person answered it in the recording („Zapisać zmiany?” OK, „Podaj powód” with a value)."""

    kind: Literal["alert", "confirm", "prompt"]
    message: str | None = Field(default=None, description="Its words, as recorded.")
    accept: bool = True
    value: Scalar | None = Field(
        default=None, description="For a prompt: what to type ('$inputs.x' for the data's)."
    )


class DocumentField(_Model):
    """For 'read' of a document image (a scan, a photo): the field read with a model that sees
    images, checked by the rules of its kind before it is used (the full Maptelo reads them)."""

    field: str = Field(min_length=1, description="The field as the document and the form name it.")
    kind: Literal["text", "code", "nip", "date", "amount", "iban", "number"] = "text"
    role: Literal["net", "vat", "gross"] | None = Field(
        default=None, description="Which amount it is, for the document's net + VAT = gross check."
    )
    typed_as: str | None = Field(
        default=None,
        description="How the form writes it: a date's pattern (%d.%m.%Y) or the value's shape "
        "with 9 for every digit (9 999,99); without it the value is typed as printed.",
    )
    compare_with: Target | None = Field(
        default=None,
        description="The field on the screen holding another reading of the same value (what "
        "OCR put in the form). A value no rule checks (a number, a date) is taken only when the "
        "two readings agree; a tax number or an account the picture does not give is taken from "
        "it when it passes its check.",
    )


class Step(_Model):
    id: Identifier
    intent: str = Field(min_length=1, description="What the step achieves, in business terms.")
    note: str | None = Field(
        default=None,
        description="What the person who showed the process said about the step, while showing "
        "it or on its map afterwards: why it is done, the rule they follow („the newest SBI”).",
    )
    note_when: str | None = Field(
        default=None,
        description="When the step is done, as the person said it („only when the invoice's "
        "amount differs from the WZ”): for people and for whoever builds the automation; a robot "
        "follows only a rule (when).",
    )
    person_decides: bool = Field(
        default=False,
        description="The person said a person decides at this step: a robot stops before it.",
    )
    alternatives: list[str] = Field(
        default_factory=list,
        description="The other decisions offered where this one was chosen („Korekta (CN)” "
        "beside „Akceptuj” in the invoice's row): no recording showed when they are made. "
        "Unless the owner says it is always this one, a person decides, or the robot makes it "
        "only while its rule ('requires') holds and stops before it otherwise.",
    )
    action: Action
    target: Target | None = None
    within: WithinRow | None = None
    value: Scalar | None = None
    document: DocumentField | None = Field(
        default=None,
        description="For 'read' with a target that is a document's image: which field of the "
        "document to read (with a model that sees images; the run needs --vision).",
    )
    save_as: Identifier | None = Field(
        default=None,
        description="Variable set by 'read' (the text) or 'download' (where the file is kept).",
    )
    after: str | None = Field(
        default=None,
        min_length=1,
        description="For 'read' without a target: the words the value follows in what the "
        "screen says, in the page or a frame of it („Zgłoszono szkodę” SZK/2026/0001., "
        "„Termin dostawy:” 2026-10-20); the value is the word after them.",
    )
    looks_like: str | None = Field(
        default=None,
        min_length=1,
        description="With 'after': what the value looks like, letters A and digits 9 (A-9 for "
        "PO-10001, 9-9-9 for a date); a word after the same words shaped otherwise is not it.",
    )
    rest: bool = Field(
        default=False,
        description="With 'after': the value is the whole rest of the message the words label "
        "(„Kontrole: Kwota poza tolerancją…”), not the one word after them.",
    )
    match: Literal["words"] | None = Field(
        default=None,
        description="For 'select_option': the option is the one whose name's words all stand in "
        "the value (the customer an e-mail names), and no other with as many; without it the "
        "value is the option's value or label.",
    )
    in_state: Identifier | None = None
    window: int = Field(
        default=0,
        ge=0,
        description="The window the step is done in: 0 the process's first, 1 the first one a "
        "step opened (a chooser, an approval), and so on.",
    )
    opens_window: bool = Field(
        default=False,
        description="The step opens a new window; the steps after it in the next window "
        "number are done there.",
    )
    closes_window: bool = Field(
        default=False,
        description="The step closes its window (a chooser, once something is chosen): "
        "its result shows in the window under it.",
    )
    dialogs: list[DialogAnswer] = Field(
        default_factory=list,
        description="Dialogs of the browser itself the step brings up, in order, and how "
        "to answer them; one that was not recorded stops the run.",
    )
    when: Predicate | None = Field(default=None, description="Guard: skip the step if false.")
    otherwise: Identifier | None = Field(
        default=None,
        description="The other way the process goes: the step is done only when the step this "
        "names was not (forward the invoice, or hold it with a reason); its 'when' is checked "
        "after that.",
    )
    requires: Predicate | None = Field(
        default=None,
        description="What every recording showed before this step (the order's lines table "
        "still empty). When the screen shows otherwise, work left from before may be on it: the "
        "run stops before the step.",
    )
    expect: Predicate | None = None
    outcomes: dict[Identifier, Predicate] | None = Field(default=None, min_length=2)
    on_outcome: dict[Identifier, OutcomeHandler] | None = None
    verify_effects: list[Identifier] = Field(default_factory=list)
    risk: RiskClass | None = None
    executor: Executor = Executor.DETERMINISTIC
    fallback: Executor | None = None
    per_line: bool = Field(
        default=False,
        description="Done once for each line of the record (an order's products): steps in a "
        "row marked so are one block, repeated line by line.",
    )
    calendar: Calendar | None = Field(
        default=None, description="For 'pick_date': how the calendar names days and months."
    )
    control: bool = Field(
        default=False,
        description="A check a person makes before confirming (four eyes: compares a request "
        "with its document, then approves it). Done by a person (executor 'human') unless the "
        "company lets the robot make it.",
    )
    clicks: int | None = Field(
        default=None,
        ge=2,
        le=2,
        description="For 'click': 2, a double click (a row of a list opens its record: WCR's "
        "requests to approve, Oracle Forms' lists).",
    )
    no_suggestion: Literal["keep_typed"] | None = Field(
        default=None,
        description="For 'choose': when no suggestion contains the value, leave it typed and "
        "go on, as people did when the application had no such entry (the next step's result "
        "tells, e.g. a message that it was not found). Without it the run stops there.",
    )
    timeout_s: float | None = Field(default=None, gt=0, le=600)
    evidence: Evidence | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        _check_action_args(self.action, self.target, self.value, words=self.after is not None)
        if self.after is not None and self.action is not Action.READ:
            raise ValueError("'after' is only valid for 'read'")
        if self.looks_like is not None and self.after is None:
            raise ValueError("'looks_like' is only valid with 'after'")
        if self.rest and (self.after is None or self.looks_like is not None):
            raise ValueError("'rest' is only valid with 'after' and without 'looks_like'")
        if self.match is not None and self.action is not Action.SELECT_OPTION:
            raise ValueError("'match' is only valid for 'select_option'")
        if self.action is Action.READ and self.save_as is None:
            raise ValueError("'save_as' is required for 'read'")
        if self.document is not None and (
            self.action is not Action.READ or self.target is None or self.after is not None
        ):
            raise ValueError(
                "'document' is only valid for 'read' with a target (the document's image) and "
                "without 'after'"
            )
        if self.save_as is not None and self.action not in (Action.READ, Action.DOWNLOAD):
            raise ValueError("'save_as' is only valid for 'read' and 'download'")
        if self.within is not None and self.target is None:
            raise ValueError("'within' narrows a 'target', so it needs one")
        if self.expect is not None and self.outcomes is not None:
            raise ValueError("use either 'expect' or 'outcomes', not both")
        if self.action is Action.WAIT and self.expect is None and self.outcomes is None:
            raise ValueError("action 'wait' needs 'expect' or 'outcomes'")
        if self.on_outcome:
            unknown = sorted(set(self.on_outcome) - set(self.outcomes or {}))
            if unknown:
                raise ValueError(
                    f"'on_outcome' refers to undeclared outcomes: {', '.join(unknown)}"
                )
        if len(set(self.verify_effects)) != len(self.verify_effects):
            raise ValueError("'verify_effects' lists an effect twice")
        if self.fallback is not None and self.fallback == self.executor:
            raise ValueError("'fallback' must differ from 'executor'")
        if self.no_suggestion is not None and self.action is not Action.CHOOSE:
            raise ValueError("'no_suggestion' is only valid for 'choose'")
        if (self.action is Action.PICK_DATE) != (self.calendar is not None):
            raise ValueError("'calendar' is required for 'pick_date' and only valid there")
        return self

    @property
    def effective_risk(self) -> RiskClass:
        if self.risk is not None:
            return self.risk
        return RiskClass.READ if self.action in READ_ONLY_ACTIONS else RiskClass.DRAFT

    def predicates(self) -> list[Predicate]:
        roots = [p for p in (self.when, self.requires, self.expect) if p is not None]
        roots += list((self.outcomes or {}).values())
        return [p for root in roots for p in root.walk()]


# --- Effects, states, interrupts, exceptions ------------------------------------------


class HttpVerifier(_Model):
    """Reads the system of record through a channel other than the screen that wrote it."""

    kind: Literal["http"] = "http"
    url: str = Field(
        min_length=1,
        description="Absolute URL or path relative to application.api_base_url; "
        "{inputs.name} placeholders allowed.",
    )
    expect: dict[str, Scalar] = Field(
        min_length=1, description="Response JSON field -> expected value ($inputs.name allowed)."
    )

    def values(self) -> list[object]:
        """What the check is made of (where the record's values go)."""
        return [self.url, *self.expect.values()]

    def describe(self) -> str:
        return self.url


class ScreenVerifier(_Model):
    """Reads the record again in the program itself, on a screen other than the one that
    wrote it, as a person checks a list after saving: a desktop program has no API. The
    screen is opened from the menu, the record's row is found in its table by the values that
    name it, and the row's cells are compared."""

    kind: Literal["screen"] = "screen"
    menu: list[str] = Field(
        min_length=2, description="The menu, then its item: ['Ceny', 'Wnioski cenowe']."
    )
    row: dict[str, Scalar] = Field(
        min_length=1,
        description="Column -> the value that names the record's row ($inputs.name allowed).",
    )
    expect: dict[str, Scalar] = Field(
        default_factory=dict,
        description="Column -> the value the record's row shows ($inputs.name allowed).",
    )
    rows: Literal["one", "all"] = Field(
        default="one",
        description="'one': the values name the record's one row; 'all': the record wrote "
        "several rows the values name (the lines of an imported file, benchmark M3), each to "
        "show what expect says.",
    )

    def values(self) -> list[object]:
        return [*self.row.values(), *self.expect.values()]

    def describe(self) -> str:
        return " > ".join(self.menu)


class PageVerifier(_Model):
    """Reads the record again on a page of the web application itself, opened afresh by its
    address after the work, as a person reloads a list to see the new row: a fresh page shows
    what the system stored, not what the screen said after saving. The same application, so
    weaker than an API of its own; proposed from the recordings and confirmed by a person,
    never assumed (the clean-Windows test of 11.10: a person who knows no API)."""

    kind: Literal["page"] = "page"
    url: str = Field(
        min_length=1,
        description="The page: a path on the application (its base_url) or an absolute "
        "address; {inputs.name} placeholders allowed.",
    )
    table: str | None = Field(default=None, description="The table's name, when one is shown.")
    row: dict[str, Scalar] = Field(
        min_length=1,
        description="Column -> the value that names the record's row ($inputs.name allowed).",
    )
    expect: dict[str, Scalar] = Field(
        default_factory=dict,
        description="Column -> the value the record's row shows ($inputs.name allowed).",
    )

    def values(self) -> list[object]:
        return [self.url, *self.row.values(), *self.expect.values()]

    def describe(self) -> str:
        return self.url


class Effect(_Model):
    """A change in the system of record that defines 'done'."""

    id: Identifier
    description: str = Field(min_length=1)
    verifier: HttpVerifier | ScreenVerifier | PageVerifier


class Idempotency(_Model):
    """If these effects already hold before a run, the work is done: skip instead of redo."""

    skip_if_effects: list[Identifier] = Field(min_length=1)


class State(_Model):
    """A screen the process can be on, recognised by its fingerprint."""

    description: str | None = None
    url: str | None = Field(
        default=None,
        description="Glob matched against the page path; a #part (key=glob&...) must match too.",
    )
    visible: Target | None = Field(default=None, description="All of these must be visible.")

    @model_validator(mode="after")
    def _has_fingerprint(self) -> Self:
        if self.url is None and self.visible is None:
            raise ValueError("a state needs 'url' and/or 'visible' to be recognisable")
        return self


INTERRUPT_ACTIONS = frozenset({Action.CLICK, Action.PRESS, Action.FILL})


class InterruptAction(_Model):
    action: Action
    target: Target | None = None
    value: Scalar | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.action not in INTERRUPT_ACTIONS:
            allowed = ", ".join(sorted(INTERRUPT_ACTIONS))
            raise ValueError(f"interrupt handlers may only use: {allowed}")
        _check_action_args(self.action, self.target, self.value)
        return self


class Interrupt(_Model):
    """A state that may appear at any moment (popup, session warning) and its handler."""

    id: Identifier
    description: str | None = None
    when: Predicate
    do: list[InterruptAction] = Field(min_length=1)
    max_per_run: int = Field(default=10, ge=1)


class ExceptionKind(StrEnum):
    BUSINESS = "business"
    SYSTEM = "system"


class ExceptionSpec(_Model):
    kind: ExceptionKind
    description: str = Field(min_length=1)
    retryable: bool | None = Field(
        default=None, description="Default: system exceptions yes, business exceptions no."
    )

    @property
    def is_retryable(self) -> bool:
        if self.retryable is not None:
            return self.retryable
        return self.kind is ExceptionKind.SYSTEM


# --- Inputs ----------------------------------------------------------------------------


class InputType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    TIME = "time"
    """A time of day („09:22”): a delivery window, the start of a shift."""
    BOOLEAN = "boolean"


NBSP = chr(0xA0)  # non-breaking space, common in pasted numbers
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_AMOUNT = re.compile(r"0(?:[.,]0+)?")
ZERO_MASK = re.compile(r"0{2,}")
LIKE_MASK = "{}%"
"""A value typed as a search: itself, then % (a list of values in Oracle Forms finds what
begins so: K0010% for the customer K0010; benchmark M1, M2). One case of a string typed with
words around it: ``typed_as`` holds the words and one {} where the value goes ("Kwota netto
niezgodna z dokumentem {}." for the delivery note WZ/2026/01018, benchmark M6)."""
"""How a number is typed to a width with its leading zeros: 000000000 for the order 000000302."""
NATIONAL = "national"
"""typed_as of a phone number typed without its country's code: +1 2058812302 as 2058812302."""
COUNTRY_CODE = re.compile(r"\+\d{1,3}[\s.-]+(?=\S)")
"""The country's code a phone number is written with, before the number itself („+48 ”)."""


def national(phone: str) -> str:
    """A phone number without the country's code it is written with (+48 600 100 200 as
    600 100 200); one written without a code, as it is."""
    text = phone.strip()
    found = COUNTRY_CODE.match(text)
    return text[found.end() :] if found else text


_TRUE = {"true", "yes", "1", "tak"}
_FALSE = {"false", "no", "0", "nie"}

InputValue = str | int | Decimal | date | time | bool


class DayShift(_Model):
    """A date the record does not give, counted from another of its dates (the old price
    line ends the day before the new one starts: ``{from: start_date, days: -1}``)."""

    from_: Identifier = Field(alias="from", description="The date input it is counted from.")
    days: int = Field(description="Days after that date; negative: before it.")


class InputSpec(_Model):
    type: InputType
    description: str | None = None
    required: bool = True
    pattern: str | None = Field(default=None, description="Full-match regex (strings only).")
    min: Decimal | None = None
    max: Decimal | None = None
    choices: list[str] | None = Field(default=None, min_length=1)
    example: Scalar | None = None
    column: str | None = Field(
        default=None,
        description="Header of the column in the records file (a sheet or CSV) that holds "
        "this value, when people take it from a table.",
    )
    typed_as: str | None = Field(
        default=None,
        description="How people type the value on screen: a date pattern such as %d.%m.%Y "
        "or %m/%d/%Y %H:%M:%S, 0.00 / 0,00 for an amount with two decimals, zeros "
        "(000000000) for a number typed to that width with its leading zeros, or national "
        "for a phone number typed without its country's code (+1 2058812302 as 2058812302).",
    )
    written_as: str | None = Field(
        default=None,
        description="How the records file writes a date as text, when not as YYYY-MM-DD: a "
        "pattern such as %m/%d/%Y (09/10/2012) or %d.%m.%Y.",
    )
    secret: bool = Field(
        default=False,
        description="A password or a key: never shown nor kept (results, logs, messages show "
        "it masked).",
    )
    per_line: bool = Field(
        default=False,
        description="One value for each line of the record (the products of an order): the "
        "steps that use it are done once per line.",
    )
    derived: DayShift | None = Field(
        default=None,
        description="A date counted from another date of the record (the day before it: "
        "days -1); the records file needs no column for it.",
    )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.derived is not None and self.type is not InputType.DATE:
            raise ValueError("'derived' is only valid for date inputs")
        if self.pattern is not None:
            if self.type is not InputType.STRING:
                raise ValueError("'pattern' is only valid for string inputs")
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"'pattern' is not a valid regex: {exc}") from exc
        numeric = self.type in (InputType.INTEGER, InputType.DECIMAL)
        if (self.min is not None or self.max is not None) and not numeric:
            raise ValueError("'min'/'max' are only valid for integer and decimal inputs")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("'min' is greater than 'max'")
        if self.choices is not None and self.type is not InputType.STRING:
            raise ValueError("'choices' are only valid for string inputs")
        if self.typed_as is not None:
            self._check_typed_as(self.typed_as)
        if self.written_as is not None and (
            self.type not in (InputType.DATE, InputType.TIME) or "%" not in self.written_as
        ):
            raise ValueError("'written_as' is a date or time pattern such as %m/%d/%Y, %I:%M%p")
        if self.example is not None:
            self.coerce(self.example)
        return self

    def _check_typed_as(self, pattern: str) -> None:
        if self.type is InputType.DATE:
            from maptelo.dates import ORACLE_MASK, ORACLE_MASK_PL

            if pattern in (ORACLE_MASK, ORACLE_MASK_PL):
                return  # Oracle Forms' mask: 01-NOV-2026, in Polish 01-LIS-2026
            if "%" not in pattern:
                raise ValueError("'typed_as' of a date is a pattern such as %d.%m.%Y")
            try:
                date(2026, 12, 1).strftime(pattern)
            except ValueError as exc:
                raise ValueError(f"'typed_as' is not a date pattern: {exc}") from exc
        elif self.type is InputType.TIME:
            if "%" not in pattern:
                raise ValueError("'typed_as' of a time is a pattern such as %I:%M %p")
        elif self.type is InputType.DECIMAL:
            if _AMOUNT.fullmatch(pattern) is None:
                raise ValueError("'typed_as' of an amount is 0, 0.00 or 0,00 (any decimals)")
        elif self.type is InputType.STRING and pattern == NATIONAL:
            return
        elif self.type is InputType.STRING and pattern.count("{}") == 1:
            return  # the value with words around it (K0010%, „… dokumentem WZ/2026/01018.”)
        elif self.type in (InputType.STRING, InputType.INTEGER):
            if ZERO_MASK.fullmatch(pattern) is None:
                raise ValueError(
                    "'typed_as' of a number typed with its leading zeros is its width in "
                    "zeros (000000000)"
                )
        else:
            raise ValueError("'typed_as' is not valid for a yes/no input")

    def on_screen(self, value: InputValue) -> str | None:
        """The value as people type it (``typed_as``); None when it is typed as plain text."""
        if self.typed_as is None:
            return None
        if self.type is InputType.DATE and isinstance(value, date):
            from maptelo.dates import ORACLE_MASK, ORACLE_MASK_PL, oracle_date

            if self.typed_as in (ORACLE_MASK, ORACLE_MASK_PL):
                return oracle_date(value, self.typed_as)
            return value.strftime(self.typed_as)
        if self.type is InputType.TIME and isinstance(value, time):
            return value.strftime(self.typed_as)
        if self.type is InputType.DECIMAL and isinstance(value, Decimal):
            separator = "," if "," in self.typed_as else "."
            places = len(self.typed_as.partition(separator)[2])
            rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
            return f"{rounded:.{places}f}".replace(".", separator)
        if self.typed_as == NATIONAL and isinstance(value, str):
            return national(value)  # +1 2058812302 typed as 2058812302
        if self.type is InputType.STRING and "{}" in self.typed_as and isinstance(value, str):
            return self.typed_as.replace("{}", value.strip())  # K0010%, words around the value
        if self.type in (InputType.STRING, InputType.INTEGER) and isinstance(value, str | int):
            digits = str(value).strip()  # 302 typed as 000000302; anything else as it is
            return digits.zfill(len(self.typed_as)) if digits.isdigit() else None
        return None

    def coerce(self, raw: object) -> InputValue:
        """Turn a raw value (CLI text, CSV cell, YAML scalar) into a typed one or raise."""
        match self.type:
            case InputType.STRING:
                value: InputValue = self._as_string(raw)
            case InputType.INTEGER:
                value = self._as_integer(raw)
            case InputType.DECIMAL:
                value = self._as_decimal(raw)
            case InputType.DATE:
                value = self._as_date(raw)
            case InputType.TIME:
                value = self._as_time(raw)
            case InputType.BOOLEAN:
                value = self._as_boolean(raw)
        if isinstance(value, int | Decimal) and not isinstance(value, bool):
            if self.min is not None and value < self.min:
                raise ValueError(f"{value} is below the minimum {self.min}")
            if self.max is not None and value > self.max:
                raise ValueError(f"{value} is above the maximum {self.max}")
        return value

    def _as_string(self, raw: object) -> str:
        if isinstance(raw, bool) or raw is None:
            raise ValueError(f"expected text, got {raw!r}")
        text = raw.isoformat() if isinstance(raw, date) else str(raw).strip()
        if self.pattern is not None and re.fullmatch(self.pattern, text) is None:
            raise ValueError(f"{text!r} does not match the pattern {self.pattern}")
        if self.choices is not None and text not in self.choices:
            raise ValueError(f"{text!r} is not one of: {', '.join(self.choices)}")
        return text

    @staticmethod
    def _as_integer(raw: object) -> int:
        if isinstance(raw, bool):
            raise ValueError(f"expected an integer, got {raw!r}")
        if isinstance(raw, int):
            return raw
        if isinstance(raw, float) and raw.is_integer():
            return int(raw)
        if isinstance(raw, str) and re.fullmatch(r"-?\d+", raw.strip()):
            return int(raw.strip())
        raise ValueError(f"expected an integer, got {raw!r}")

    @staticmethod
    def _as_decimal(raw: object) -> Decimal:
        if isinstance(raw, bool) or not isinstance(raw, int | float | str | Decimal):
            raise ValueError(f"expected a number, got {raw!r}")
        text = str(raw).strip().replace(NBSP, "").replace(" ", "")
        if "," in text and "." not in text:
            text = text.replace(",", ".")  # decimal comma, e.g. 129,90
        try:
            number = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"expected a number, got {raw!r}") from None
        if not number.is_finite():
            raise ValueError(f"expected a finite number, got {raw!r}")
        return number

    def _as_date(self, raw: object) -> date:
        if isinstance(raw, date):
            return raw
        if isinstance(raw, str) and _ISO_DATE.match(raw.strip()):
            try:
                return date.fromisoformat(raw.strip())
            except ValueError:
                pass
        if isinstance(raw, str) and self.written_as is not None:  # the sheet's own way
            try:
                return datetime.strptime(raw.strip(), self.written_as).date()
            except ValueError:
                pass
        written = f" or {self.written_as}" if self.written_as else ""
        raise ValueError(f"expected a date as YYYY-MM-DD{written}, got {raw!r}")

    def _as_time(self, raw: object) -> time:
        if isinstance(raw, time):
            return raw
        if isinstance(raw, datetime):
            return raw.time()
        if isinstance(raw, str):
            for pattern in [self.written_as, "%H:%M", "%H:%M:%S"]:
                if pattern is None:
                    continue
                try:
                    return datetime.strptime(raw.strip(), pattern).time()
                except ValueError:
                    continue
        written = f" or {self.written_as}" if self.written_as else ""
        raise ValueError(f"expected a time as HH:MM{written}, got {raw!r}")

    @staticmethod
    def _as_boolean(raw: object) -> bool:
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValueError(f"expected true/false, got {raw!r}")


# --- The process -----------------------------------------------------------------------


class Application(_Model):
    name: str = Field(min_length=1)
    kind: Literal["web", "java"] = "web"
    """``java``: a program on the desktop, seen and driven through the Java Access Bridge."""
    window: str | None = Field(
        default=None,
        description="For a Java program: a part of its main window's title, to find it "
        "('SRK', 'Oracle Applications').",
    )
    base_url: str | None = None
    api_base_url: str | None = None
    timezone: str | None = Field(
        default=None,
        description="Time zone the process is done in (IANA, e.g. Europe/Warsaw); runs use it, "
        "so a date typed on screen means the same as when people type it.",
    )
    locale: str | None = Field(
        default=None, description="Browser language the process is done in, e.g. pl-PL."
    )


class RecordsSpec(_Model):
    """Where the rows of a batch come from when people work from a table (a sheet of a
    workbook or a CSV file): one run per row. Inputs name their ``column``; other columns
    of the table are left alone."""

    description: str | None = None
    sheet: str | None = Field(
        default=None, description="Sheet of the workbook (default: the first one)."
    )
    one_run_per: list[str] = Field(
        default_factory=list,
        description="Columns that name one record when several rows make it (an order and its "
        "products): rows with the same values are one run, each row one of its lines.",
    )


class ProcessCard(_Model):
    """What the process is for, in the words of the people who do it: what no recording shows
    (Maptelo Lite asks for it after recording; the SOP and the AI brief start with it)."""

    story: str | None = Field(
        default=None,
        description="The process in the person's own words, as told to someone new on the team: "
        "where the data comes from, what is done in which program, what goes otherwise.",
    )
    goal: str | None = Field(default=None, description="What the process achieves, and for whom.")
    data: str | None = Field(
        default=None, description="Where its values come from (a sheet, a mail, a portal)."
    )
    scope: str | None = Field(
        default=None, description="What a robot may do, and what stays with a person."
    )
    done: str | None = Field(
        default=None, description="How one knows the work is done, and where one checks it."
    )
    failures: str | None = Field(
        default=None, description="What goes wrong at times, and what is done then."
    )
    never: str | None = Field(default=None, description="What must never be done.")

    def answered(self) -> dict[str, str]:
        """The questions answered: field -> answer."""
        return {
            k: v.strip() for k, v in self.model_dump().items() if isinstance(v, str) and v.strip()
        }


CARD_FIELDS = ("story", "goal", "data", "scope", "done", "failures", "never")


class ProcessModel(_Model):
    """An executor-independent description of one business process."""

    schema_version: Annotated[Literal["0.1"], BeforeValidator(_version_as_text)]
    id: Identifier
    version: int = Field(ge=1, description="Revision of this process model.")
    title: str = Field(min_length=1)
    description: str | None = None
    card: ProcessCard | None = Field(
        default=None, description="What the process is for, as the people who do it say."
    )
    application: Application
    preconditions: list[str] = Field(
        default_factory=list, description="What must hold before the process starts."
    )
    inputs: dict[Identifier, InputSpec] = Field(default_factory=dict)
    records: RecordsSpec | None = Field(
        default=None, description="The table people take the inputs from, row by row."
    )
    private: bool = Field(
        default=False,
        description="Screens show personal or confidential data: screenshots cover what is "
        "typed and what tables hold, and the model keeps no values from recordings.",
    )
    effects: list[Effect] = Field(default_factory=list)
    idempotency: Idempotency | None = None
    states: dict[Identifier, State] = Field(default_factory=dict)
    interrupts: list[Interrupt] = Field(default_factory=list)
    exceptions: dict[Identifier, ExceptionSpec] = Field(default_factory=dict)
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def _references_resolve(self) -> Self:
        from maptelo.model.integrity import find_integrity_issues

        issues = find_integrity_issues(self)
        if issues:
            raise ValueError("broken references:\n" + "\n".join(f"  - {i}" for i in issues))
        return self

    def step(self, step_id: str) -> Step:
        return next(s for s in self.steps if s.id == step_id)

    def waits_for_person(self) -> Step | None:
        """The first step a person makes, always (no condition), after a step that writes: a
        record the robot started would wait there half done, and the same sheet run again
        would write its first part twice (benchmark p10). The robot does not start it."""
        written = False
        for step in self.steps:
            if written and step.executor is not Executor.DETERMINISTIC and step.when is None:
                return step
            if step.effective_risk in (RiskClass.COMMIT, RiskClass.IRREVERSIBLE):
                written = True
        return None


Predicate.model_rebuild()
