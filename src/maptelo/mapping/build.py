"""Building a process model from one normalized recording.

What one recording can and cannot tell is kept honest: every value the person typed or
chose becomes an input (constants need more recordings, M4); a row-choice rule, risk class
and interrupts are guesses, listed in ``notes`` for the person to confirm.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from itertools import combinations, pairwise
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from maptelo import options, sentences
from maptelo.consent import CONSENT
from maptelo.data.tables import Table, TableError, read_table
from maptelo.dates import read_day
from maptelo.mapping import shown
from maptelo.mapping.choices import offered_choices
from maptelo.mapping.naming import Lang, human_title, say, slug, unique, written_date
from maptelo.mapping.normalize import (
    Act,
    Normalized,
    calendar_ladder,
    normalize,
    one_time_code,
)
from maptelo.mapping.shown import ANY_WORD
from maptelo.mapping.sources import bind, is_search, trace_origins
from maptelo.model.integrity import PLACEHOLDER
from maptelo.model.schema import ProcessModel
from maptelo.model.urls import fill_from, origin, screen_template
from maptelo.trace.aria import AriaNode, parse_aria, table_row_nodes, table_rows
from maptelo.trace.schema import DialogSeen, ElementInfo, Trace, TraceEvent, TraceState

_COMMIT_WORDS = re.compile(
    r"\b(save|submit|apply|confirm|send|post|book|approve|reject|create|update|delete|issue|"
    r"register|zapisz|zatwierdź|zatwierdz|wyślij|wyslij|potwierdź|potwierdz|zaksięguj|"
    r"zaksieguj|księguj|ksieguj|usuń|usun|utwórz|utworz|wystaw|rejestruj|zarejestruj|"
    r"akceptuj|zaakceptuj|odrzuć|odrzuc|wstrzymaj|przekaż|przekaz|importuj|zaimportuj)\b",
    re.IGNORECASE,
)
"""Words of a button that saves, when the recording cannot say (it did not see what was sent)."""
_FILTER_WORDS = re.compile(r"\b(filters?|filtr\w*|search|szukaj|wyszukaj)\b", re.IGNORECASE)
"""Words of a button that only narrows a list down („Apply Filters”, WebArena-Verified): no save
by its words alone; one that sent data saves all the same (``sent_by``)."""
_AREAS = {"region", "article", "document", "main", "group", "complementary", "note"}
"""Parts of a page with a name of their own, whose text a robot can read whole (an e-mail's
„Treść wiadomości”)."""
_DATE_LIKE = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{4})$")
"""A date in a row: with a name, it says which of the name's rows (the request from 1 Nov)."""
_IRREVERSIBLE_WORDS = re.compile(
    r"\b(send|sign|pay|transfer|publish|wyślij|wyslij|podpisz|zapłać|zaplac|przelej|"
    r"opublikuj)\b",
    re.IGNORECASE,
)
"""What cannot be taken back once done: sending (an invoice to KSeF, a reminder), signing,
paying, publishing."""
_DISMISS = re.compile(r"\b(nie|no|anuluj|cancel|zamknij|close|wróć|wroc|back)\b", re.IGNORECASE)
_CONSENT = CONSENT
"""A window asking for the consents of a site (cookies, privacy): its answer is no write of
the process, though it sends the choice (benchmark M5: „Pliki cookie i zgody”)."""
_YES = re.compile(r"tak|yes", re.IGNORECASE)
"""The answer that does what a question asks."""
"""Buttons that close a window without doing what it asks."""
_ATTESTS = re.compile(
    r"zgodn|sprawdzi|sprawdzon|zweryfikow|weryfikac|potwierdzam|oświadczam|oswiadczam|"
    r"zatwierdzam|przejrza|porówna|porowna|\bverif|\bchecked\b|\bi confirm|\bi certify|"
    r"\bmatch(es)?\b|\breviewed\b|\bcompared\b",
    re.IGNORECASE,
)
"""A box a person ticks to say they checked something ("Pozycje zgodne z dokumentem
źródłowym", "Sprawdzono z fakturą"): a control, which a robot cannot truly make."""
_APPROVES = re.compile(
    r"^(za)?akceptuj|^zatwierd[zź]|^odrzu[cć]|^podpisz|^approve|^accept\b|^reject|^sign\b",
    re.IGNORECASE,
)
"""A button that approves (or rejects) what someone else asked for."""
_APPROVALS = re.compile(r"akceptac|zatwierdz|wniosk|wniosek|oczekuj|approv|pending", re.IGNORECASE)
"""A screen of things waiting for someone's approval ("Wnioski do akceptacji")."""
_NO_UNDO = re.compile(
    r"nie można (tego )?cofnąć|nie mozna (tego )?cofnac|nieodwracaln|cannot be undone|"
    r"can't be undone|irreversible",
    re.IGNORECASE,
)
_AMOUNT_WORDS = (
    "price",
    "amount",
    "qty",
    "quantity",
    "total",
    "rate",
    "cena",
    "kwota",
    "ilo",
    "warto",
)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUMBER = re.compile(r"^-?\d+(?:[.,]\d+)?$")
_ID_LIKE = re.compile(r"^[A-Za-z]{0,4}[-_ ]?\d+[A-Za-z0-9-]*$")
JAVA = "java"
"""The scheme of a Java program's screens in a trace (``java://srk/Cennik klienta``)."""
_TITLE_SEPARATOR = "[·|" + re.escape("-" + chr(0x2013)) + "]"  # middle dot, bar, dashes


@dataclass
class MapResult:
    model: ProcessModel
    trace: Trace
    step_events: dict[str, list[int]] = field(default_factory=dict)
    """Step id -> trace event numbers it came from (for screenshots in documents)."""
    notes: list[str] = field(default_factory=list)
    """What one recording could not establish; for a person to confirm."""
    seen_after: dict[str, list[str]] = field(default_factory=dict)
    """Step id -> the words its value follows in what the screen says of the field's item
    („przyjechało” of „37241-E: przyjechało 20 szt.”); the recordings together choose one."""


# --- screens (states) ------------------------------------------------------------------


def _template(url: str) -> str:
    return screen_template(url)


def _screen_key(url: str) -> tuple[str, str]:
    """A screen of one application: two applications may both have a ``/`` or a ``/login``."""
    return origin(url), _template(url)


def _app_name(trace: Trace) -> str:
    if trace.header.program:
        return trace.header.program  # a Java program: as its main window names it
    titles = [e.title for e in trace.events if e.title]
    split = [re.split(rf" {_TITLE_SEPARATOR} ", t) for t in titles]
    ends = Counter(parts[-1].strip() for parts in split if len(parts) > 1)
    starts = Counter(parts[0].strip() for parts in split if len(parts) > 1)
    best = max(
        [*ends.most_common(1), *starts.most_common(1)], key=lambda item: item[1], default=None
    )
    if best is not None:
        return best[0]  # the part that stays the same across screens is the application
    return urlsplit(trace.header.start_url).hostname or "application"


def _screen_title(title: str | None, app: str) -> str | None:
    if not title:
        return None
    clean = re.sub(rf"\s*{_TITLE_SEPARATOR}\s*{re.escape(app)}\s*$", "", title).strip()
    clean = re.sub(rf"^\s*{re.escape(app)}\s*{_TITLE_SEPARATOR}\s*", "", clean).strip()
    if clean == app:
        return None
    # a number names one record's screen; a record's value marked as such (_MARK) does not,
    # but a title that is nothing else („70011-B”) names the record, not the screen
    unmarked = _MARK.sub("", clean)
    if not re.search(r"[^\W\d_]", unmarked):
        return None
    return clean if not any(ch.isdigit() for ch in unmarked) else None


def _marks(
    aria: AriaNode, named: Callable[[str | None], str | None] | None = None
) -> list[dict[str, str]]:
    """What can tell a screen from the others, best first: a table, a heading, a field;
    ``named`` marks the record's values in a name (a heading that is the record's title)."""

    def of(name: str) -> str:
        return (named(name) or name) if named is not None else name

    def numbered(name: str) -> bool:  # a number names one record's screen, a marked value not
        return any(ch.isdigit() for ch in _MARK.sub("", name))

    found = []
    for node in aria.walk():  # "Tabela 182/A/NBP/2026 z dnia 2026-10-06" names one day's table
        if node.role == "table" and node.name and not numbered(of(node.name)):
            found.append({"role": "table", "name": of(node.name)})
    for node in aria.walk():
        if node.role == "heading" and node.name and not numbered(of(node.name)):
            found.append({"role": "heading", "name": of(node.name)})
    for node in aria.walk():
        if node.role in ("textbox", "combobox") and node.name:
            found.append({"role": node.role, "name": node.name})
    return found


def _landmark(
    arias: list[AriaNode], named: Callable[[str | None], str | None] | None = None
) -> dict[str, str] | None:
    """The best mark every look at the screen shows: an empty list's „Pokonaj konkurencję
    zachwycającymi ofertami!” is gone once a filter is cleared and the list has rows, it tells
    nothing about the screen (Odoo, benchmark p12)."""
    if not arias:
        return None
    first, *others = arias
    for mark in _marks(first, named):
        if all(mark in _marks(other, named) for other in others):
            return mark
    return None


@dataclass
class _Screen:
    key: str
    title: str | None
    landmark: dict[str, str] | None
    templates: set[str] = field(default_factory=set)


_SEPARATORS = "/·|\\-" + chr(0x2013)  # slash, middle dot, bar, dashes
_SEGMENT = rf"(?:^|(?<=\s[{_SEPARATORS}]\s))"
_SEGMENT_END = rf"(?=$|\s[{_SEPARATORS}]\s)"
_MARK = re.compile(r"\x01([^\x02]*)\x02")
"""A value of the record in a screen's title or heading, as kept until its input is named."""


_MARKS_MAY = "[" + "".join(map(chr, (0xAE, 0x2122, 0xA9, 0x2120))) + "]?"
"""A word of a name may carry a registered or trade mark on screen that the sheet leaves out."""


class _Screens:
    """The screens of a recording, by their address; a window over the main one (a chooser, an
    approval) has screens of its own, also at the main page's address (benchmark g039)."""

    def __init__(
        self, trace: Trace, app: str, skip: set[int], sheet: Mapping[str, str] | None = None
    ) -> None:
        self.app = app
        self.screens: dict[str, _Screen] = {}
        self._by_url: dict[tuple[str, str, int], str] = {}
        self.typed: dict[str, str] = {}
        """Values a person typed or chose in the recording, by the field's name: a screen named
        by one (after saving, the heading is the page title just typed: WebArena-Verified, CMS
        pages) is one screen for every record, not a screen of this record's value."""
        for event in trace.events:
            if event.type not in ("fill", "select") or not event.value or event.secret:
                continue
            value = event.value.strip()
            if len(value) < 4 or value.isdigit():
                continue
            target = event.target
            named = (target.label or target.name or target.field) if target else None
            self.typed.setdefault(value, (named or "value").strip())
        for value, column in (sheet or {}).items():  # the record's values from its sheet
            if len(value.strip()) >= 4 and not value.strip().isdigit():
                self.typed.setdefault(value.strip(), column)
        titles: dict[tuple[str, str, int], str | None] = {}
        looks: dict[tuple[str, str, int], list[str]] = {}
        """Every snapshot of each screen: its mark is one they all show."""
        for event in trace.events:
            url = event.url
            if event.type == "navigate":
                landed = trace.state(event.state_after)
                url = landed.url if landed is not None else url  # e.g. a bookmark rewritten
            if not url or event.seq in skip:
                continue
            key = (*_screen_key(url), event.window)
            titles[key] = titles.get(key) or event.title
            shots = looks.setdefault(key, [])
            state_id = event.state_before if event.is_action else event.state_after
            state = trace.state(state_id)
            same_page = (
                state is not None
                and _screen_key(state.url) == key[:2]
                and state.window == event.window
            )
            if state is not None and same_page and state.aria not in shots:
                shots.append(state.aria)
        for key, title in titles.items():
            self.add(key, title, looks[key])

    def add(self, where: tuple[str, str, int], title: str | None, arias: list[str]) -> None:
        if where[0].startswith(f"{JAVA}://"):
            # a Java screen is its frame or window, as its title names it (the program's own
            # main window: the program); never the first field on it
            named = human_title(where[1].strip("/"))
            screen_title: str | None = named if named.strip("… ") else self.app
        else:
            screen_title = _screen_title(self._named(title), self.app)
        landmark = _landmark([parse_aria(text) for text in arias if text], self._named)
        key = screen_title or (f"{landmark['role']}:{landmark['name']}" if landmark else where[1])
        if where[2] and (where[0], where[1], 0) in self._by_url and landmark is not None:
            key = f"{landmark['role']}:{landmark['name']}"  # the window's own, not the page's
        screen = self.screens.setdefault(key, _Screen(key, screen_title, landmark))
        screen.templates.add(where[1])
        self._by_url[where] = key

    def _named(self, words: str | None) -> str | None:
        """A title or heading with a value the person typed (a whole part of it, between the
        title's separators) marked as the record's (``_MARK``)."""
        if not words:
            return words
        for value in sorted(self.typed, key=len, reverse=True):
            # in any letters and with the shop's ® or ™ („Teton Pullover Hoodie” for the sheet's
            # „Teton pullover hoodie”, WebArena-Verified 242), as the run finds it
            loose = r"\s+".join(re.escape(word) + _MARKS_MAY for word in value.split())
            pattern = re.compile(_SEGMENT + loose + _SEGMENT_END, re.IGNORECASE)
            marked = "\x01" + value + "\x02"
            words = pattern.sub(lambda _, marked=marked: marked, words)  # type: ignore[misc]
        return words

    def _plain(self, words: str) -> str:
        """The words for a person: the field's name in brackets for the record's value."""
        return _MARK.sub(lambda m: f"[{self.typed.get(m.group(1), 'value')}]", words)

    def state_id(self, url: str | None, window: int = 0) -> str | None:
        if not url:
            return None
        key = self._by_url.get((*_screen_key(url), window)) or self._by_url.get(
            (*_screen_key(url), 0)
        )
        return self._ids().get(key) if key else None

    def _ids(self) -> dict[str, str]:
        taken: set[str] = set()
        ids = {}
        for key, screen in self.screens.items():
            if screen.title:
                base = slug(self._plain(screen.title))
            else:
                shortest = min(screen.templates, key=len)
                words = [w for w in shortest.split("/") if w and w != "*"]
                base = slug("_".join(words)) if words else "screen"
            ids[key] = unique(base, taken)
        return ids

    def title_of(self, url: str | None, window: int = 0) -> str:
        where = _screen_key(url or "")
        key = self._by_url.get((*where, window)) or self._by_url.get((*where, 0))
        screen = self.screens.get(key) if key else None
        if screen and screen.title:
            return self._plain(screen.title)
        if screen and screen.landmark:
            return self._plain(screen.landmark["name"])
        return urlsplit(url or "").path or "/"

    def states(self, names: Mapping[str, str] | None = None) -> dict[str, dict[str, Any]]:
        """The screens as the model's states; ``names``: a typed value -> the input that holds
        it, so a heading of the record's value is looked for as this record's value."""
        names = names or {}

        def bound(words: str) -> str:
            return _MARK.sub(
                lambda m: (
                    "{inputs." + names[m.group(1)] + "}" if m.group(1) in names else m.group(1)
                ),
                words,
            )

        result: dict[str, dict[str, Any]] = {}
        for key, state_id in self._ids().items():
            screen = self.screens[key]
            templates = sorted(screen.templates)
            prefix = os.path.commonprefix(templates)
            if "*" in prefix:
                url = prefix[: prefix.index("*")] + "*"
            elif len(templates) > 1:
                url = prefix + "*"
            else:
                url = templates[0]
            entry: dict[str, Any] = {"url": url}
            if screen.title:
                entry["description"] = self._plain(screen.title)
            if screen.landmark:
                entry["visible"] = [{**screen.landmark, "name": bound(screen.landmark["name"])}]
            result[state_id] = entry
        return result


# --- inputs ----------------------------------------------------------------------------


def _typed_as(kind: str, value: str) -> str | None:
    """How people typed an amount: with a decimal comma (6,04 -> ``0,00``) or point, as
    many decimals as they wrote; a run types the value the same way."""
    if kind != "decimal":
        return None
    match = re.fullmatch(r"-?\d+([.,])(\d+)", value.strip())
    if match is None:
        return None
    return "0" + match.group(1) + "0" * len(match.group(2))


def _infer_type(label: str, value: str) -> str:
    text = value.strip()
    if _ISO_DATE.match(text):
        return "date"
    if _NUMBER.match(text):
        amount = any(word in label.lower() for word in _AMOUNT_WORDS)
        if amount or re.search(r"[.,]", text):
            return "decimal"
    return "string"


# --- rows ------------------------------------------------------------------------------


RowRule = Literal["rule", "key", "all", "sorted"]
"""How a row was told apart: by a rule ("Status = Active"), by a value that names one record
and so comes from the work list ("Numer = PO/2026/0001"), or only by all of its values."""


def _row_rule(trace: Trace, act: Act) -> tuple[dict[str, str], RowRule]:
    """Pick the column that explains which row was chosen. A word that singles the row out
    is a rule; else a number or a code that does is the record's key, a value to take from the
    work list, never a constant (that would open the same record for every row)."""
    target = act.event.target
    assert target is not None
    assert target.row is not None
    cells = {k: v for k, v in target.row.cells.items() if v and not k.startswith("#")}
    state = trace.state(act.event.state_before)
    rows: list[dict[str, str]] = []
    if state is not None:
        table = parse_aria(state.aria).find("table", target.row.table)
        rows = table_rows(table) if table else []

    def preference(item: tuple[str, str]) -> int:
        value = item[1]
        if _ISO_DATE.match(value) or _NUMBER.match(value):
            return 3
        if _ID_LIKE.match(value) or any(ch.isdigit() for ch in value):
            return 2
        return 0

    def unique(column: str, value: str) -> bool:
        return sum(1 for row in rows if row.get(column) == value) == 1

    for column, value in sorted(cells.items(), key=preference):
        if preference((column, value)) > 0:
            break
        if unique(column, value):
            return {column: value}, "rule"
    for column, value in cells.items():
        if preference((column, value)) == 2 and unique(column, value):
            return {column: value}, "key"
    return cells, "all"


def _rows_before(trace: Trace, act: Act, name: str | None) -> int | None:
    """Data rows of the table the act picked a row from, as the screen showed them."""
    screen = _screen_before(trace, act)
    table = screen.find("table", name or None) if screen is not None else None
    return len(table_rows(table)) if table is not None else None


def _screen_before(trace: Trace, act: Act) -> AriaNode | None:
    state = trace.state(act.event.state_before)
    return parse_aria(state.aria) if state is not None else None


def _result_url(act: Act, window: int | None) -> str | None:
    """The address the act led to: its last navigation before a message it brought up was
    shown. A person who read „Dodano pozycję” and then went to the list by its address went on
    by themselves: the list is no result of „Dodaj pozycję” (benchmark p16)."""
    url = None
    for observed in act.observed:
        if observed.type == "appeared" and url is not None:
            break
        if observed.type == "navigated" and observed.url and window in (None, observed.window):
            url = observed.url
    return url


def _table_ladder(trace: Trace, act: Act, name: str | None) -> list[dict[str, str]]:
    """The table a row is picked from: by its caption, and as the only table on the screen
    when it was the only one (an update may rename the caption)."""
    if not name:
        return [{"role": "table"}]
    screen = _screen_before(trace, act)
    alone = screen is not None and len(screen.find_all("table")) == 1
    return [{"role": "table", "name": name}, *([{"role": "table"}] if alone else [])]


_NUMBERED = re.compile(r"_\d+$")
_ENTRIES = ("fill", "select_option", "choose", "upload", "pick_date")


def _form_name(step: dict[str, Any]) -> str:
    """The name the form sends a step's field under, without its numbers: a line's field
    typed again for the next line has the same (``lines[1].qty`` is ``lines[0].qty``), a
    password and its confirmation do not (``PASSWORD``, ``CONFIRM_PASSWORD``, benchmark p15)."""
    names = [str(r["field"]) for r in step.get("target") or [] if r.get("field")]
    return re.sub(r"\d+", "", names[0]) if names else ""


def repeated_block(keys: list[tuple[str, ...]]) -> tuple[int, int, int] | None:
    """The block of steps done again and again in a row (start, length, times): the one that
    covers the most steps, the shortest such when two do."""
    best: tuple[int, int, int] | None = None
    for length in range(1, len(keys) // 2 + 1):
        for start in range(len(keys) - 2 * length + 1):
            block, times = keys[start : start + length], 1
            while keys[start + times * length : start + (times + 1) * length] == block:
                times += 1
            if times < 2:
                continue
            cover = length * times
            if best is None or cover > best[1] * best[2]:
                best = (start, length, times)
    return best


def _read_tables(name: str | None, aria: str) -> list[dict[str, str]]:
    """The table a value is read from: by a caption that names the table, not one day's
    ("Tabela 182/A/NBP/2026 z dnia 2026-10-06"), and as the only table on the screen."""
    named = bool(name) and not any(ch.isdigit() for ch in name or "")
    ladder = [{"role": "table", "name": name or ""}] if named else []
    if len(parse_aria(aria).find_all("table")) == 1:
        ladder.append({"role": "table"})
    return ladder


def _alone_in_row(trace: Trace, act: Act, target: ElementInfo) -> bool:
    """Whether the clicked element was the only one of its kind in its row (the only link):
    found that way, it is found after an update renames it."""
    screen = _screen_before(trace, act)
    if screen is None or target.row is None or not target.role:
        return False
    table = screen.find("table", target.row.table or None)
    if table is None:
        return False
    wanted = {k: v for k, v in target.row.cells.items() if v and not k.startswith("#")}
    for row, values in table_row_nodes(table):
        if wanted and all(values.get(k) == v for k, v in wanted.items()):
            return sum(1 for node in row.walk() if node.role == target.role) == 1
    return False


# --- building --------------------------------------------------------------------------


def _row_has_data(target: ElementInfo) -> bool:
    """Whether the row holds anything besides the clicked element ("Add a line" does not)."""
    assert target.row is not None
    own = (target.name or target.text or "").strip()
    return any(v and v.strip() != own for v in target.row.cells.values())


def _clicked_value(target: ElementInfo) -> bool:
    """The person clicked a value in a named column (a record picked by what it shows).
    A cell is a value even when the rest of its row is empty; a button that fills a row
    on its own ("Add a line") is a command."""
    if target.row is None or not target.column or target.role in ("option", "menuitem"):
        return False
    own = (target.name or target.text or "").strip()
    in_its_cell = target.row.cells.get(target.column, "").strip() == own
    is_value = target.role in ("cell", "gridcell") or _row_has_data(target)
    return bool(own) and in_its_cell and is_value


_COMMAND = re.compile(
    r"^(wybierz|edytuj|otwórz|otworz|pokaż|pokaz|szczegóły|szczegoly|usuń|usun|podgląd|"
    r"select|choose|pick|edit|open|view|show|details|delete|remove)\b",
    re.IGNORECASE,
)
"""A button saying what it does to its row: a command, never what names the row."""


def _command_of_every_row(trace: Trace, act: Act, target: ElementInfo) -> bool:
    """A text the column shows in every row („Wybierz” in „Akcje”) does not tell rows
    apart: it is a command, and the row is picked by a rule (benchmark g031). When the
    screen around it was not recorded (a window of its own), a button saying what it does
    is one too."""
    own = (target.name or target.text or "").strip()
    screen = _screen_before(trace, act)
    table = screen.find("table", target.row.table or None) if screen and target.row else None
    if table is not None:
        shown = [row.get(target.column or "", "").strip() for row in table_rows(table)]
        if len(shown) >= 2:
            return all(value == own for value in shown)
    return target.role in ("button", "link") and bool(_COMMAND.match(own))


_ASKS = re.compile(
    r"^(podaj|wpisz|wprowadź|wprowadz|uzupełnij|uzupelnij|please enter|enter|type|give)\s+",
    re.IGNORECASE,
)
"""How a prompt asks („Podaj powód zmiany”): the rest names the value."""


def _sorted_edge(trace: Trace, act: Act, target: ElementInfo) -> Literal["first", "last"] | None:
    """The first or the last row of a table shown sorted by a column (aria-sort): the newest (or
    the oldest) of the list, whichever record that is each time; not the record the recording
    happened to take (benchmark M5: the newest invoice, sorted by its date)."""
    row = target.row
    if row is None or not row.sorted_by or row.index is None:
        return None
    count = _rows_before(trace, act, row.table)
    if row.index == 0:
        return "first"
    if count is not None and count > 1 and row.index == count - 1:
        return "last"
    return None


ORDER_WORDS = {
    "pl": {"ascending": "rosnąco", "descending": "malejąco"},
    "en": {"ascending": "ascending", "descending": "descending"},
}


_PICKS = re.compile(r"^(wybierz|wybór|select|choose|pick)\b", re.IGNORECASE)


def row_command(target: ElementInfo) -> str | None:
    """The words of the button or link a row's step clicks, when they say more than „pick
    this row” (Akceptuj, Korekta (CN), Podgląd: benchmark M5, M6); None for Select, Wybierz."""
    if target.role not in ("button", "link"):
        return None
    words = (target.text or target.name or "").strip()
    return words if words and _PICKS.match(words) is None else None


def _picks_row(target: ElementInfo) -> bool:
    """A command inside a data row (Select, Edit): the row is chosen by a rule."""
    return target.role not in ("option", "menuitem") and _row_has_data(target)


def keep_private(data: dict[str, Any]) -> None:
    """A private model: no value a person typed stays in it as an example."""
    data["private"] = True
    for spec in data.get("inputs", {}).values():
        spec.pop("example", None)


def _same_window(act: Act, following: Act | None) -> bool:
    """The person's next action is in the window this one was in: it did not close (the
    screen read after a row's click can be the one under the list window, read as its OK
    closed it: benchmark D05)."""
    if following is None or following.event.window < act.event.window:
        return False
    here, there = act.event.target, following.event.target
    return here is not None and there is not None and here.dialog == there.dialog


def _locators(target: ElementInfo, *, drop_row_css: bool) -> list[dict[str, Any]]:
    """The ways to find an element; a path through row numbers only when nothing else is
    known (it finds whatever is in that row later)."""
    every = [candidate.model_dump(exclude_none=True) for candidate in target.candidates]
    if not drop_row_css:
        return every
    found = [c for c in every if not (c.get("css") and "nth-of-type" in c["css"])]
    return found or every


def _words_around(aria: str, value: str) -> str | None:
    """The words a value stands with on a screen, when one text there holds it: those after it
    („6 records found”: records found), else those before it; None otherwise. A table's rows
    and cells are not such texts (the review 346 of a list is not „346 records found”)."""
    pattern = re.compile(r"(?<!\S)" + re.escape(value) + r"(?!\S)")
    texts = {
        shown.plain(text)
        for node in parse_aria(aria).walk()
        if node.role not in ("row", "cell", "gridcell", "columnheader", "rowheader")
        for text in (node.name, node.value)
        if text
    }
    holding = [text for text in texts if text != value and pattern.search(text)]
    if len(holding) != 1:
        return None
    match = pattern.search(holding[0])
    assert match is not None
    after, before = holding[0][match.end() :].split(), holding[0][: match.start()].split()
    words = [w.strip(".,;:!?()[]") for w in (after[:3] or before[-3:])]
    return " ".join(w for w in words if w) or None


_PATH_PARTS = re.compile(r"\s*(?:>|\||→|»)\s*")
"""What separates the parts of a value written as a path (a menu's „Plik > Zapisz jako”); not
a slash, which a document's number has („ZW/2026/002”)."""
_NAMED_BY_DATA = ("button", "link", "tab", "menuitem", "option", "radio", "checkbox", "treeitem")
"""What a person clicks by its words, which may be a value of the record."""
_NO_ROLE = (None, "presentation", "none", "generic")
"""Roles that say an element has none (jQuery UI's tab links are „presentation”): it is
clicked by its words."""


def _exception_from(message: str, placeholders: dict[str, str]) -> tuple[str, str]:
    """(id, description) for an error message; typed values become {input} placeholders."""
    description = message.strip()
    for value, name in sorted(placeholders.items(), key=lambda item: -len(item[0])):
        if value and value in description:
            description = description.replace(value, f"{{{name}}}")
    words = re.sub(r"\{[^}]*\}", " ", description).split()
    return slug(" ".join(words[:7]) or "rejected"), description


class _Builder:
    def __init__(
        self,
        normalized: Normalized,
        lang: Lang,
        process_id: str | None,
        written: Mapping[int, str | Mapping[str, Any]] | None = None,
        sheet: bool = True,
    ) -> None:
        self.n = normalized
        self.sheet = sheet
        """Whether the inputs take their columns from the sheet the recording names."""
        self.written = dict(written or {})
        """Descriptions written by an action of the step (on the map afterwards, or on Studio's
        list of steps while recording): they replace what was said in the box."""
        self.trace = normalized.trace
        self.lang = lang
        self.app = _app_name(self.trace)
        login_seqs = {a.seq for a in normalized.by_role("login")}
        self.trace_sheet = self.sheet_values()
        self.screens = _Screens(self.trace, self.app, login_seqs, self.trace_sheet)
        self.process_id = slug(process_id or self.trace.header.process or "mapped_process")
        self.recording = self.trace.header.recording_id
        self.notes: list[str] = []
        self.step_events: dict[str, list[int]] = {}
        self.seen_after: dict[str, list[str]] = {}
        self.inputs: dict[str, dict[str, Any]] = {}
        self.inputs_by_field: dict[str, str] = {}
        self.labelled: dict[str, list[str]] = {}
        self.passwords: dict[tuple[str, int], str] = {}
        """(the page, which password of it) -> its input: a password typed again is the same."""
        """The inputs typed into fields of each label: two „Rabat” fields of one form, typed
        from two columns of the sheet, are two inputs."""
        self._columns: dict[str, str] | None = None
        self.placeholders: dict[str, str] = {}
        """Typed value -> input name, to turn values inside messages into placeholders."""
        self.exceptions: dict[str, dict[str, Any]] = {}
        self._step_ids: set[str] = set()
        self._input_names: set[str] = set()
        self._picked_labels: list[str] = []
        """The fields of the dates picked so far: a range picks two days for one field."""
        self._attested_on: str | None = None
        """The screen where a box saying "checked against the document" was ticked."""
        self._control_noted: str | None = None
        self.forget_shared_actions()

    def forget_shared_actions(self) -> None:
        """A button's name tells what it does only when no other button has it: two buttons
        named "action", told apart by their value („Dodaj pozycję”, „Zapisz zamówienie”,
        benchmark p02), are found by their words, never by that name (after a reorder it
        named the other one, and the run stopped). The recorder no longer records such a
        name; this forgets it in older recordings, where different buttons share it."""
        buttons: dict[str, set[tuple[str | None, str | None]]] = {}
        for event in self.trace.events:
            if event.target is not None and event.target.action:
                buttons.setdefault(event.target.action, set()).add(
                    (event.target.role, event.target.name)
                )
        shared = {action for action, named in buttons.items() if len(named) > 1}
        for event in self.trace.events:
            target = event.target
            if target is not None and target.action in shared:
                target.action = None
                target.candidates = [c for c in target.candidates if c.action is None]

    def note(self, pl: str, en: str) -> None:
        self.notes.append(pl if self.lang == "pl" else en)

    def person_notes(self, steps: list[dict[str, Any]]) -> None:
        """What the person said about a step goes with it: said while recording (Studio's box),
        it belongs to the act it came after; said after an act the map has no step for (a
        misclick), to the next step; written on the map afterwards, it replaces what was said."""
        said: dict[int, list[str]] = {}
        for act in self.n.acts:
            for seen in act.observed:
                if seen.type == "note" and seen.value and seen.value.strip():
                    said.setdefault(act.seq, []).append(seen.value.strip())
        owner = {seq: step["id"] for step in steps for seq in self.step_events.get(step["id"], [])}
        kept = set(owner.values())
        firsts = sorted((min(s), i) for i, s in self.step_events.items() if s and i in kept)
        by_step: dict[str, list[str]] = {}
        for seq, texts in sorted(said.items()):
            step_id = owner.get(seq) or next((i for first, i in firsts if first > seq), None)
            step_id = step_id or (steps[-1]["id"] if steps else None)
            if step_id is not None:
                by_step.setdefault(step_id, []).extend(texts)
        for step in steps:
            seqs = sorted(self.step_events.get(step["id"], []))
            written = next((self.written[s] for s in seqs if s in self.written), None)
            if written is not None:  # an empty one takes back what was said
                full = said_of(written)
                if full["text"]:
                    step["note"] = full["text"]
                if full["when"]:
                    step["note_when"] = full["when"]
                if full["person"]:  # a person decides there: the robot stops before it
                    step["person_decides"] = True
                    step["executor"] = "human"
            elif step["id"] in by_step:
                step["note"] = " ".join(by_step[step["id"]])

    def evidence(self, seqs: list[int], note: str | None = None) -> dict[str, Any]:
        evidence: dict[str, Any] = {"traces": [f"{self.recording}#{s}" for s in seqs]}
        if note:
            evidence["note"] = note
        return evidence

    def typed_inputs(self) -> dict[str, str]:
        """A typed value -> the input that holds it (its example): a screen named by the value
        is looked for by this record's value of that input."""
        found: dict[str, str] = {}
        for name, spec in self.inputs.items():
            example = spec.get("example")
            if isinstance(example, str) and example.strip():
                found.setdefault(example.strip(), name)
            column = spec.get("column")
            for value, held_in in self.trace_sheet.items():
                if column and held_in == column:
                    found.setdefault(value, name)  # the record's value from the input's column
        return found

    def input_for(self, act: Act) -> str:
        page = (act.event.url or "", act.event.secret_no or 0)
        if act.event.secret and act.event.secret_no and page in self.passwords:
            return self.passwords[page]  # the password again („Verify password”): one value
        label = act.field_name or "value"
        value = act.event.value or ""
        column = self.column_of(value)
        words = act.event.option_label if act.kind == "select" else None
        if column is None and words and (by_words := self.column_of(words)) is not None:
            # the sheet holds the option's words („Federal Express”), the list sends its code
            # („fedex”, WebArena's Magento): the record's value is the words, and a list is
            # chosen by its words as well as by its codes
            value, column = words, by_words
        for known in self.labelled.get(label, []):
            example = str(self.inputs[known].get("example", ""))
            if value != example and is_search(example, value):
                continue  # the value typed again as a search („26386%” after „26386-F” in the
                # same field, benchmark M2): typed so, an input of its own
            held = self.column_of(example)
            if column is None or held is None or held == column:
                return known  # the same field again, or its value of the record's next line
        again = label in self.labelled  # another field of the label: named by its column
        plain_label = PLACEHOLDER.sub("", label).strip(" :") or "value"  # „Ilość do zwrotu”
        by_column = again and column is not None
        name = unique(slug(str(column) if by_column else plain_label), self._input_names)
        described = f"{label} ({column})" if by_column else label
        spec: dict[str, Any] = {"type": _infer_type(label, value), "description": described}
        if value:
            spec["example"] = value
        typed_as = _typed_as(spec["type"], value)
        if typed_as is not None:
            spec["typed_as"] = typed_as
        if act.event.secret:  # a password typed into the work: from the sheet, never shown
            spec["secret"] = True
            if act.event.secret_no:
                self.passwords[page] = name
        once = one_time_code(act)
        if once:  # new every time: never an example, a constant or a column of the sheet
            spec.pop("example", None)
            spec.update({"secret": True, "required": False})
        if act.kind == "select" and act.event.option_label and act.event.option_label != value:
            # the list sends a code („fedex”): its words say what was chosen
            spec["description"] = f"{label} ({act.event.option_label})"
        self.inputs[name] = spec
        self.inputs_by_field.setdefault(label, name)
        self.labelled.setdefault(label, []).append(name)
        if value and not once:
            self.placeholders[value] = name
        return name

    def column_of(self, value: str) -> str | None:
        """The one column of the sheet the person worked from that holds the value."""
        if self._columns is None:
            self._columns = self.sheet_columns()
        return self._columns.get(shown.plain(value)) if value.strip() else None

    def each_rows(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """A box ticked or unticked one after another in rows of one table, when those rows
        are all the rows that show something in one column (Importuj unticked in each row
        with an error, benchmark M3): one step done in each such row. Kept apart, each named
        its row by what it held, and the next file has its errors in other rows."""
        out: list[dict[str, Any]] = []
        i = 0
        while i < len(steps):
            j = i + 1
            while j < len(steps) and _same_in_rows(steps[i], steps[j]):
                j += 1
            merged = self.each_of(steps[i:j]) if j - i >= 2 else None
            out += [merged] if merged is not None else steps[i:j]
            i = j
        return out

    def each_of(self, run: list[dict[str, Any]]) -> dict[str, Any] | None:
        first = run[0]
        within = first["within"]
        rows = self.rows_before(first, within)
        taken = self.rows_taken(run, rows) if rows else None
        if not rows or taken is None or len(taken) != len(run) or len(taken) == len(rows):
            return None  # rows not read, one row twice, or every row: no rule of rows
        acted = {str(loc.get("column")) for loc in first.get("target") or []}
        said = [column for step in run for column in step["within"].get("where") or {}]
        column = next(
            (
                c
                for c in dict.fromkeys([*said, *rows[0]])
                if c not in acted
                and {i for i, row in enumerate(rows) if row.get(c, "").strip()} == taken
            ),
            None,
        )
        if column is None:
            return None  # the rows taken are not the rows that show something in one column
        table = next((loc.get("name") for loc in within["table"] if loc.get("name")), "")
        seqs = [s for step in run for s in self.step_events.get(str(step["id"]), [])]
        merged = dict(first)
        merged["within"] = {"table": within["table"], "where_not": {column: None}, "pick": "each"}
        merged["intent"] = say(
            self.lang, "each_row", what=first["intent"], table=table or "?", column=column
        )
        merged["evidence"] = self.evidence(seqs)
        self.step_events[str(first["id"])] = seqs
        for step in run[1:]:
            self.step_events.pop(str(step["id"]), None)
        return merged

    def rows_taken(self, run: list[dict[str, Any]], rows: list[dict[str, str]]) -> set[int] | None:
        """The rows of the table the steps were done in: the row showing what the recording
        saw in it, else the row at its place."""
        events = {e.seq: e for e in self.trace.events}
        taken: set[int] = set()
        for step in run:
            seqs = self.step_events.get(str(step["id"])) or []
            target = events[seqs[0]].target if seqs and seqs[0] in events else None
            if target is None or target.row is None:
                return None
            seen = {k: " ".join(v.split()) for k, v in target.row.cells.items()}
            fits = [
                i
                for i, row in enumerate(rows)
                if all(
                    " ".join(row.get(k, "").split()) == v
                    for k, v in seen.items()
                    if k != target.column
                )
            ]
            index = target.row.index
            if len(fits) == 1:
                taken.add(fits[0])
            elif index is not None and 0 <= index < len(rows):
                taken.add(index)
            else:
                return None
        return taken

    def rows_before(
        self, step: dict[str, Any], within: dict[str, Any]
    ) -> list[dict[str, str]] | None:
        """The rows of the step's table on the screen before its first action."""
        seqs = self.step_events.get(str(step["id"])) or []
        event = next((e for e in self.trace.events if seqs and e.seq == seqs[0]), None)
        state = self.trace.state(event.state_before) if event is not None else None
        if state is None:
            return None
        name = next((loc.get("name") for loc in within["table"] if loc.get("name")), None)
        node = parse_aria(state.aria).find("table", name)
        return table_rows(node) if node is not None else None

    def fold_lines(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Steps done one after another for each product of an order (choose the product,
        type its quantity, "Dodaj pozycję") are one block done per line of the record, and
        their values are one per line: the copies were steps only some orders have, and the
        sheet's row for each product was never taken (benchmark: loop_unrolled)."""
        keys: list[tuple[str, ...]] = [
            (str(s["action"]), _NUMBERED.sub("", str(s["id"])), _form_name(s), str(s.get("value")))
            for s in steps
        ]
        found = repeated_block(keys)
        if found is None:
            return steps
        start, length, times = found
        block = steps[start : start + length]
        if not any(s["action"] in _ENTRIES for s in block):
            return steps  # clicked again and again ("next month"): not lines of a record
        if all(s["action"] == "pick_date" for s in block):
            return steps  # days of one calendar (a stay from - to): dates of one record
        for step in block:
            step["per_line"] = True
            for value in [step.get("value"), *(step.get("within") or {}).get("where", {}).values()]:
                name = (
                    str(value).removeprefix("$inputs.") if str(value).startswith("$inputs.") else ""
                )
                if name in self.inputs:
                    self.inputs[name]["per_line"] = True
        first, last = block[0]["intent"], block[-1]["intent"]
        self.note(
            f"Kroki od „{first}” do „{last}” powtórzono {times} razy, po jednym razie na "
            "pozycję: to jeden blok, który robot robi dla każdej pozycji rekordu.",
            f"The steps from “{first}” to “{last}” were done {times} times, once a line: one "
            "block the robot does for each line of the record.",
        )
        return steps[: start + length] + steps[start + length * times :]

    def file_input(self, act: Act, label: str) -> str:
        """The file a person chose: a path the data has to give (a column of the sheet),
        unless the process downloaded that file before (``link_downloads``)."""
        name = unique(slug(f"plik_{label}"), self._input_names)
        spec: dict[str, Any] = {"type": "string", "description": label}
        if act.event.files:
            spec["example"] = ", ".join(act.event.files)
        self.inputs[name] = spec
        return name

    def link_downloads(self, steps: list[dict[str, Any]], acts: list[Act]) -> None:
        """A file uploaded after the process downloaded it (the courier's label, uploaded to
        the order) is that file: the upload takes it from the download, not from the sheet
        (benchmark: upload_not_recorded)."""
        by_seq = {seq: step for step in steps for seq in self.step_events.get(step["id"], [])}
        given: dict[str, dict[str, Any]] = {}
        for act in acts:
            step = by_seq.get(act.seq)
            if step is None:
                continue
            if act.kind == "upload" and act.event.files:
                source = given.get(act.event.files[0].casefold())
                reference = str(step.get("value", ""))
                if source is not None and reference.startswith("$inputs."):
                    name = reference.removeprefix("$inputs.")  # named by the field, not the file
                    variable = source.setdefault("save_as", name)
                    step["value"] = f"$vars.{variable}"
                    self.inputs.pop(name, None)
            for seen in act.observed:
                if seen.type == "downloaded" and step.get("action") == "download":
                    given.update({name.casefold(): step for name in seen.files})

    def value_input(self, column: str, value: str) -> str:
        """An input for a value the person picked by clicking it in a table: the one it was
        typed as when it was searched for first (benchmark D05: the invoice's number typed
        into "Szukaj", then its row clicked), else a new one named for the column."""
        if column in self.inputs_by_field:
            return self.inputs_by_field[column]
        typed = self.placeholders.get(value)
        if typed is not None and typed in self.inputs and len(value.strip()) >= 3:
            return typed
        name = unique(slug(column), self._input_names)
        spec: dict[str, Any] = {"type": _infer_type(column, value), "description": column}
        if value:
            spec["example"] = value
            self.placeholders[value] = name
        self.inputs[name] = spec
        self.inputs_by_field[column] = name
        self.labelled.setdefault(column, []).append(name)
        return name

    def sorted_intent(self, edge: str | None, target: ElementInfo) -> str:
        assert target.row is not None
        order = ORDER_WORDS[self.lang].get(target.row.sort_order or "", target.row.sort_order or "")
        command = row_command(target)
        return say(
            self.lang,
            f"row_{edge or 'first'}" + ("_command" if command else ""),
            table=target.row.table or "",
            column=target.row.sorted_by or "",
            order=order,
            **({"command": command} if command else {}),
        )

    def data_in_row(self, act: Act, target: ElementInfo) -> tuple[str, str] | None:
        """(column, input) of a cell of the picked row holding a value of the data, so the
        row is the one with the record's value, not the recorded one:
        - typed earlier in the process: the code searched for in a chooser („Kod lub nazwa”:
          K0028, then the row with Kod K0028);
        - in the sheet the person worked from, and telling the row from the others: the
          employee whose request „Akceptuj” approves (benchmark p13)."""
        assert target.row is not None
        cells = [
            (column, value.strip())
            for column, value in target.row.cells.items()
            if value and value.strip() and not column.startswith("#")
        ]
        typed = {
            value.strip().casefold(): name
            for value, name in self.placeholders.items()
            if len(value.strip()) >= 3 and name in self.inputs
        }
        for column, value in cells:
            if (name := typed.get(value.casefold())) is not None:
                return column, name
        sheet = self.sheet_cells()
        if not sheet:
            return None
        screen = _screen_before(self.trace, act)
        table = screen.find("table", target.row.table or None) if screen is not None else None
        rows = table_rows(table) if table is not None else []
        for column, value in cells:
            if shown.measure(value):
                continue  # a price, a date: what the row says, not what names it (p01)
            same = sum(1 for row in rows if (row.get(column) or "").strip() == value)
            from_sheet = shown.plain(value).casefold() in sheet and shown.distinctive(value)
            if from_sheet and (not rows or same == 1):
                return column, self.value_input(column, value)
        return None

    def entry_row(self, act: Act, target: ElementInfo) -> dict[str, Any] | None:
        """The row a value is typed into, in a table of fields (Oracle Forms' block of lines):
        the smallest set of the record's values that names one row on the screen before it,
        the field itself still empty when that is what tells the new line from an old one of
        the same item; for a row that was all empty, the first empty row (the new line at the
        end). None when nothing names the row (benchmark D06: End Date in the item's old line,
        then the new line's Product Value, Value and Start Date)."""
        assert target.row is not None
        own = target.column or ""
        cells = {k: (v or "").strip() for k, v in target.row.cells.items() if not k.startswith("#")}
        screen = _screen_before(self.trace, act)
        table = screen.find("table", target.row.table or None) if screen is not None else None
        rows = table_rows(table) if table is not None else []
        conditions: list[tuple[str, str | None, str]] = self.data_cells(cells, own)
        if own and not cells.get(own):
            conditions.append((own, None, ""))  # still empty: a new line, not the old one
        for size in range(1, len(conditions) + 1):
            chosen = conditions[:size]
            fits = sum(
                1
                for row in rows
                if all(
                    (row.get(c) or "").strip() == (v if ref is not None else "")
                    for c, ref, v in chosen
                )
            )
            if fits == 1:
                return {"where": {c: ref for c, ref, _ in chosen}}
        if not any(cells.values()) and own:  # a new line: the first empty one
            return {"where": {own: None}, "pick": "first"}
        return None

    def data_cells(self, cells: dict[str, str], own: str) -> list[tuple[str, str | None, str]]:
        """(column, $inputs.x, what it shows) of the row's cells that hold the record's values:
        typed earlier in the process, or in the sheet the person worked from."""
        typed = {
            value.strip().casefold(): name
            for value, name in self.placeholders.items()
            if len(value.strip()) >= 3 and name in self.inputs
        }
        sheet = self.sheet_cells()
        found: list[tuple[str, str | None, str]] = []
        for column, value in cells.items():
            if column == own or not value:
                continue
            if (name := typed.get(value.casefold())) is not None:
                found.append((column, f"$inputs.{name}", value))
            elif sheet and shown.plain(value).casefold() in sheet and shown.distinctive(value):
                found.append((column, f"$inputs.{self.value_input(column, value)}", value))
        return found

    def from_data(self, value: str) -> bool:
        """Typed earlier in the process or in the sheet the person worked from."""
        text = shown.plain(value).casefold()
        typed = {shown.plain(v).casefold() for v in self.placeholders}
        return bool(text) and (text in typed or text in self.sheet_cells())

    def row_named_by_data(self, act: Act, target: ElementInfo) -> dict[str, str] | None:
        """{column: input} of the cells of the picked row that the sheet holds and that
        together tell it from the other rows: the customer's name and the date of a draft
        request whose own number (clicked) is no value of the work (benchmark p16). A name is
        needed; a date or a code beside it is taken too, so a row of the same customer for
        another date is not the one. None when the sheet does not name the row."""
        assert target.row is not None
        screen = _screen_before(self.trace, act)
        table = screen.find("table", target.row.table or None) if screen is not None else None
        rows = table_rows(table) if table is not None else []
        record = self.sheet_row_of(target.row.cells)
        if record is None or not rows:
            return None
        cells: list[tuple[str, str, str, bool]] = []  # column, shown, the sheet's, a date
        for column, value in target.row.cells.items():
            text = shown.plain(value)
            if column == target.column or column.startswith("#") or not text:
                continue
            if text in record and not shown.measure(text) and shown.distinctive(text):
                cells.append((column, text, text, False))
                continue
            day = read_day(text)  # „28.10.2026 09:00:00” for the sheet's 2026-10-28 (p13)
            sheet_day = day is not None and day[0].isoformat()
            if sheet_day and sheet_day in record:
                cells.append((column, text, sheet_day, True))
        if all(is_day for *_, is_day in cells):
            return None  # only dates (or nothing): they do not name a record
        for size in range(len(cells), 0, -1):  # all the record's values the row shows
            for chosen in combinations(cells, size):
                if all(is_day for *_, is_day in chosen):
                    continue
                same = sum(
                    1
                    for row in rows
                    if all(shown.plain(row.get(c) or "") == text for c, text, *_ in chosen)
                )
                if same == 1:
                    return {
                        column: self.typed_as_input(value)
                        or self.value_input(self.column_of(value) or column, value)
                        for column, _, value, _ in chosen
                    }
        return None

    def link_named_by_data(self, act: Act, target: ElementInfo) -> tuple[str, str] | None:
        """(the sheet's column, its input) of a link in a row that is a value of the record
        when nothing else of the row names it: the subject of an order e-mail („Zamówienie
        PO-10001”) in an inbox whose cells have no headers (benchmark p11)."""
        own = shown.plain(target.name or target.text or "")
        column = self.column_of(own) if own else None
        if column is None or not shown.names_one(own):
            return None
        if self.data_in_row(act, target) is not None or self.row_named_by_data(act, target):
            return None  # the row is named by its cells: picked by them, as before
        return column, self.typed_as_input(own) or self.value_input(column, own)

    def named_by_data(self, target: ElementInfo | None) -> tuple[str, str] | None:
        """(the sheet's column, its input) of an element outside a table whose own words are
        a value of the record as the sheet writes it: the button „Yes” or the option „Kelli”
        the task names (MiniWoB++). One column of the sheet holds it, or none is meant."""
        if target is None or target.row is not None:
            return None
        own = shown.plain(target.name or target.text or "")
        made = (
            bool(target.pointer)
            or target.tag in ("a", "button")
            or (target.role is not None and target.role not in _NO_ROLE)
        )
        # one letter is the record's too when it is all an element made to be clicked shows
        # (a pie menu's „H”, MiniWoB++ click-pie)
        column = self.column_of(own) if len(own) >= 2 or (own and made) else None
        if column is None and target.role == "button" and shown.CLOSE_NAMES.match(own):
            row = self.record_row() or {}  # the cross the record names („x”) is this button
            crosses = [c for c, v in row.items() if shown.plain(v).casefold() in shown.CLOSE_MARKS]
            if len(crosses) == 1:
                column, own = crosses[0], shown.plain(row[crosses[0]])
        if column is None:
            return None
        return column, self.typed_as_input(own) or self.value_input(column, own)

    def item_named_by_data(self, target: ElementInfo) -> tuple[str, str] | None:
        """(the sheet's column, its input) of the one word of a clickable whole (``item``) that
        is a value of the record: the sender of an e-mail clicked at its subject."""
        own = shown.plain(target.name or target.text or "")
        hits = {
            (word, column)
            for word in (shown.plain(w) for w in target.item or [])
            if len(word) >= 2 and word != own and (column := self.column_of(word)) is not None
        }
        if len(hits) != 1:
            return None
        word, column = next(iter(hits))
        return column, self.typed_as_input(word) or self.value_input(column, word)

    def path_part(self, target: ElementInfo) -> str | None:
        """The record's value written as a path („Linzy>Fawn”, „Plik > Zapisz jako”) whose
        part is the clicked element's name: the element is the record's."""
        own = shown.plain(target.name or target.text or "")
        row = self.record_row() if own else None
        for value in (row or {}).values():
            parts = [shown.plain(p) for p in _PATH_PARTS.split(value or "")]
            if len(parts) > 1 and own in parts:
                return shown.plain(value)
        return None

    def named_in_part(self, target: ElementInfo | None) -> tuple[str, str, str] | None:
        """(the column, its input, the words with it marked) of an element outside a table
        whose words hold one value of the record's own row as a word of their own („Tab #1”
        for the row's 1): a column the process uses nowhere else, so the value says which
        element it is. The induction asks the owner unless the recordings prove it."""
        if target is None or target.row is not None:
            return None
        own = shown.plain(target.name or target.text or "")
        row = self.record_row()
        if not own or row is None:
            return None
        typed = {  # a value the person typed anywhere in the recording: that column is in use
            shown.plain(a.event.value or "")
            for a in self.n.acts
            if a.kind in ("fill", "select") and a.event.value
        }
        hits = []
        for word in re.finditer(r"[^\W_]+", own):
            columns = [c for c, v in row.items() if shown.plain(v) == word.group()]
            if len(columns) == 1 and word.group() != own and word.group() not in typed:
                hits.append((word, columns[0]))
        if len(hits) != 1:
            return None
        word, column = hits[0]
        name = self.value_input(column, word.group())
        marked = own[: word.start()] + "{inputs." + name + "}" + own[word.end() :]
        return column, name, marked

    def record_row(self) -> dict[str, str] | None:
        """The row of the sheet this recording worked on: its only row, or the one row holding
        the values the person typed; None when no row stands out."""
        data, path = self.trace.header.data, self.trace.path
        if data is None or path is None:
            return None
        try:
            table: Table = read_table(path.parent / data.file, data.sheet)
        except (TableError, OSError):
            return None
        if len(table.rows) == 1:
            return dict(table.rows[0])
        typed = {
            shown.plain(a.event.value or "")
            for a in self.n.acts
            if a.kind in ("fill", "select") and a.event.value
        }
        holding = [r for r in table.rows if typed & {shown.plain(v) for v in r.values() if v}]
        return dict(holding[0]) if len(holding) == 1 else None

    def typed_as_input(self, value: str) -> str | None:
        """The input a value was typed from earlier in the process (a code searched for)."""
        name = self.placeholders.get(value)
        return name if name is not None and name in self.inputs else None

    def sheet_row_of(self, cells: dict[str, str]) -> set[str] | None:
        """The values of the sheet's row the picked row shows most of (the record the person
        worked on): only its values name the row, not another record's that the list also
        shows. None without a sheet or when no row's value is shown."""
        data, path = self.trace.header.data, self.trace.path
        if data is None or path is None:
            return None
        try:
            table: Table = read_table(path.parent / data.file, data.sheet)
        except (TableError, OSError):
            return None
        shown_texts = {shown.plain(v) for v in cells.values() if v and v.strip()}
        shown_days = {
            day[0].isoformat() for v in cells.values() if v and (day := read_day(shown.plain(v)))
        }
        best: set[str] | None = None
        score = 0
        for row in table.rows:
            values = {shown.plain(v) for v in row.values() if v and v.strip()}
            hits = len(values & shown_texts) + len(values & shown_days)
            if hits > score:
                best, score = values, hits
        return best

    def windows_and_dialogs(self, steps: list[dict[str, Any]], acts: list[Act]) -> None:
        """Where each step was done (a chooser, an approval in a window of its own; how deep,
        maptelo.windows) and how the browser's own dialogs it brought up were answered
        (benchmark g031-g040). The step before the first one in a deeper window opens it."""
        for index, (step, act) in enumerate(zip(steps, acts, strict=True)):
            if act.event.window:
                step["window"] = act.event.window
                after = self.trace.states.get(act.event.state_after or "")
                following = acts[index + 1] if index + 1 < len(acts) else None
                if (
                    after is not None
                    and after.window < act.event.window
                    and not _same_window(act, following)
                ):
                    step["closes_window"] = True  # what it shows next is under it
            dialogs = [o.dialog for o in act.observed if o.type == "dialog" and o.dialog]
            if dialogs:
                step["dialogs"] = [self.dialog_answer(dialog) for dialog in dialogs]
        for step, later in pairwise(steps):
            if later.get("window", 0) > step.get("window", 0):
                step["opens_window"] = True

    def dialog_templates(self, steps: list[dict[str, Any]]) -> None:
        """A value of the record inside what a dialog asks („Usunąć zamówienie
        ZA/2026/0012?”) is the record's: the run asks the same of its own record."""
        known = sorted(
            ((v, n) for v, n in self.placeholders.items() if len(v) >= 3 and n in self.inputs),
            key=lambda item: -len(item[0]),
        )
        for step in steps:
            for dialog in step.get("dialogs", []):
                message = dialog.get("message")
                for value, name in known if message else ():
                    whole = rf"(?<!\w){re.escape(value)}(?!\w)"  # a word, not part of one
                    message = re.sub(whole, f"{{inputs.{name}}}", message)
                if message:
                    dialog["message"] = message

    def dialog_answer(self, seen: DialogSeen) -> dict[str, Any]:
        """OK or Cancel, as the person answered; what they typed into a prompt is a value of
        the data (the reason for a change, from the sheet), named after what the prompt
        asked for („Podaj powód zmiany” → „Powód zmiany”)."""
        answer: dict[str, Any] = {"kind": seen.kind, "accept": seen.accepted}
        if seen.message:
            answer["message"] = seen.message
        if seen.kind == "prompt" and seen.accepted and seen.value is not None:
            asked = _ASKS.sub("", seen.message).strip(" :?.") or "Odpowiedź"
            name = self.value_input(asked[:1].upper() + asked[1:], seen.value)
            answer["value"] = f"$inputs.{name}"
        return answer

    def step_id(self, base: str) -> str:
        return unique(slug(PLACEHOLDER.sub("", base)), self._step_ids)

    def name_fields_by_data(self) -> None:
        """A field named by a value of the record (the return's quantity typed into „Ilość do
        zwrotu: 37241-E”, the product the sheet's row names, benchmark p19): its name holds
        the value's input instead ({inputs.indeks}), so each record types into its own
        product's field; the ways to find it by position (#return-qty_1) are dropped, they name
        the first product's field."""
        columns = self.sheet_columns()
        if not columns:
            return
        for act in self.n.acts:
            target = act.event.target
            if act.kind not in ("fill", "select", "choose", "check", "uncheck") or target is None:
                continue
            words = target.label or target.name
            if not words:
                continue
            found = {
                (column, value)
                for value, column in columns.items()
                if shown.names_one(value)
                and re.search(rf"(?<![\w-]){re.escape(value)}(?![\w-])", words)
            }
            if len(found) != 1:
                continue
            ((column, value),) = found
            if shown.plain(act.event.value or "").casefold() == value.casefold():
                continue  # the value typed is the one named: no field named by it
            name = self.value_input(column, value)
            mark = "{inputs." + name + "}"
            ways = []
            for rung in target.candidates or []:
                said = rung.model_dump(exclude_none=True)
                if any(isinstance(v, str) and value in v for v in said.values()):
                    named = {k: v.replace(value, mark) if isinstance(v, str) else v
                             for k, v in said.items()}  # fmt: skip
                    ways.append(rung.model_validate(named))
            act.event = act.event.model_copy(
                update={
                    "target": target.model_copy(
                        update={
                            "name": (target.name or "").replace(value, mark) or None,
                            "label": (target.label or "").replace(value, mark) or None,
                            "candidates": ways,
                        }
                    )
                }
            )

    def sheet_values(self) -> dict[str, str]:
        """Each value of the sheet the person worked from, as written, with the one column
        holding it: a screen may be named by one (the page title from the sheet)."""
        data, path = self.trace.header.data, self.trace.path
        if data is None or path is None:
            return {}
        try:
            table: Table = read_table(path.parent / data.file, data.sheet)
        except (TableError, OSError):
            return {}
        seen: dict[str, set[str]] = {}
        for row in table.rows:
            for column, value in row.items():
                if value and value.strip():
                    seen.setdefault(value.strip(), set()).add(column)
        return {value: next(iter(cols)) for value, cols in seen.items() if len(cols) == 1}

    def bind_sources(self) -> dict[str, Any] | None:
        """The inputs whose values came from the sheet the person worked from: their columns,
        and how the screen wants them typed (K0010% searched for, 01-LIS-2026). A map of one
        recording is the work list's one row: a value two columns hold is left unbound, and
        the map says which to confirm. None: no sheet, or nothing of it typed."""
        data, path = self.trace.header.data, self.trace.path
        if data is None or path is None:
            return None
        try:
            table: Table = read_table(path.parent / data.file, data.sheet)
        except (TableError, OSError):
            return None
        examples = {
            n: str(s["example"]) for n, s in self.inputs.items() if s.get("example") is not None
        }
        found = trace_origins([examples], [table])
        if not found.origins:
            return None
        row = next((r for r in found.rows if r is not None), {})
        for name, source in found.origins.items():
            if name in self.inputs:
                bind(self.inputs[name], source, row)
        for name, origins in found.doubtful.items():
            if name not in self.inputs:
                continue
            columns = ", ".join(f"„{o.column}”" for o in origins)
            label = self.inputs[name].get("description", name)
            self.note(
                f"Wartość pola „{label}” jest w kilku kolumnach arkusza ({columns}): "
                "potwierdź, z której ją brać.",
                f"The value of “{label}” is in several columns of the sheet ({columns}): "
                "say which one it comes from.",
            )
        return {"description": Path(data.file).name, "sheet": data.sheet}

    def sheet_columns(self) -> dict[str, str]:
        """Each value of the sheet the person worked from, with the one column holding it
        (a value in two columns names none of them)."""
        data, path = self.trace.header.data, self.trace.path
        if data is None or path is None:
            return {}
        try:
            table: Table = read_table(path.parent / data.file, data.sheet)
        except (TableError, OSError):
            return {}
        seen: dict[str, set[str]] = {}
        for row in table.rows:
            for column, value in row.items():
                if value and value.strip():
                    seen.setdefault(shown.plain(value), set()).add(column)
        return {value: next(iter(cols)) for value, cols in seen.items() if len(cols) == 1}

    def warned_no_undo(self, act: Act) -> bool:
        """The window the button is in says that what it does cannot be taken back."""
        target = act.event.target
        state = self.trace.state(act.event.state_before)
        if target is None or not target.dialog or state is None:
            return False
        window = parse_aria(state.aria).find("dialog", target.dialog)
        if window is None:
            return False
        said = " ".join(n.name or n.value or "" for n in window.walk())
        return _NO_UNDO.search(said) is not None

    def sent_by(self, act: Act) -> list[str]:
        """What the action, and the tries of it the application refused, sent to the
        application, as the recording saw it."""
        events = {e.seq: e for e in self.trace.events}
        tries = [events[s] for a in act.attempts for s in a.event_seqs if s in events]
        return [what for event in (act.event, *tries) for what in event.sent]

    def expectation(self, act: Act, following: Act | None) -> dict[str, Any] | None:
        """What shows the act worked, in the window its result shows in: the one it opened
        (a print preview after a save), or the one under the chooser it closed."""
        result = self.trace.states.get(act.event.state_after or "")
        window = result.window if result is not None else act.event.window
        before = self.screens.state_id(act.event.url, act.event.window)
        after_url = _result_url(act, window)
        after = self.screens.state_id(after_url, window)
        if after is not None and after != before:
            return {"state": after}
        if act.appeared("status", window=window):
            return {"visible": {"role": "status"}}
        dialogs = [
            o
            for o in act.appeared("dialog", "alertdialog", window=window)
            if o.target and o.target.name
        ]
        if dialogs and dialogs[-1].target is not None:
            return {"visible": {"role": "dialog", "name": dialogs[-1].target.name}}
        if result is not None and act.event.window and result.window < act.event.window:
            return None  # it closed its window: what is under it was there all along
        if following is not None and following.picked is not None:
            return None  # a day picked in a calendar: that day is the record's, not a result
        if following is not None and following.event.target is not None:
            nxt = following.event.target
            state_before = self.trace.state(act.event.state_before)
            # A search can show a version chooser on the same URL. The row's number is
            # record-specific, but the newly shown table is an observable outcome.
            if nxt.row is not None and nxt.row.table and state_before is not None:
                table_name = nxt.row.table
                if parse_aria(state_before.aria).find("table", table_name) is None:
                    return {"visible": {"role": "table", "name": table_name}}
            # a row's cell or a value typed earlier names this record: another record shows
            # other words there (benchmark D05: the invoice found by "Znajdź")
            data_named = nxt.row is not None or (nxt.name or "").strip() in self.placeholders
            # a menu's item shows when the person opens the menu: the next step, not this one's
            # result (benchmark D06: "Save" in File after typing Start Date)
            in_menu = nxt.role == "menuitem" and bool(nxt.column)  # an item of a menu bar's menu
            if (
                nxt.role
                and nxt.name
                and state_before is not None
                and not data_named
                and not in_menu
            ):
                if ANY_WORD in nxt.name:  # an item's field: by its words, any item
                    words = re.compile(r"\S+".join(map(re.escape, nxt.name.split(ANY_WORD))))
                    was_there = next(
                        (
                            node
                            for node in parse_aria(state_before.aria).walk()
                            if node.role == nxt.role and words.fullmatch(node.name or "")
                        ),
                        None,
                    )
                else:
                    was_there = parse_aria(state_before.aria).find(nxt.role, nxt.name)
                if was_there is None:
                    shown = {"visible": {"role": nxt.role, "name": nxt.name}}
                    if nxt.field:  # its words may change in an update; the form's name rarely
                        return {"any": [shown, {"visible": {"field": nxt.field}}]}
                    return shown
        return None

    def outcomes_for(self, act: Act, expect: dict[str, Any] | None, step: dict[str, Any]) -> None:
        """Turn known rejections into outcomes that raise business exceptions."""
        rejections = [(a.message, a.values) for a in act.attempts if a.message]
        alerts = act.appeared("alert")
        ends_here = act is self.n.steps[-1]
        if ends_here and alerts and alerts[-1].target and alerts[-1].target.text:
            rejections.append((alerts[-1].target.text, {}))
            self.note(
                f"Nagranie kończy się po kroku „{step['intent']}” komunikatem: "
                f"{alerts[-1].target.text}",
                f"The recording ends after “{step['intent']}” with the message: "
                f"{alerts[-1].target.text}",
            )
        if not rejections:
            if expect is not None:
                step["expect"] = expect
            return
        outcomes: dict[str, Any] = {"done": expect or {"not": {"visible": {"role": "alert"}}}}
        handlers: dict[str, Any] = {}
        for message, values in rejections:
            placeholders = dict(self.placeholders)
            for field_name, value in values.items():
                if field_name in self.inputs_by_field:
                    placeholders[value] = self.inputs_by_field[field_name]
            exception_id, description = _exception_from(message, placeholders)
            if exception_id == "done":
                exception_id = "rejected"
            self.exceptions.setdefault(
                exception_id, {"kind": "business", "description": description}
            )
            # Two business exceptions must not both match every alert. Keep the longest
            # literal part of the message, excluding the demonstrated record's values.
            pieces = [p.strip() for p in re.split(r"\{[^}]*\}", description) if p.strip()]
            message_words = max(pieces, key=len, default=message.strip())
            outcomes[exception_id] = {
                "all": [{"visible": {"role": "alert"}}, {"visible": {"text": message_words}}]
            }
            handlers[exception_id] = {"raise": exception_id}
        step["outcomes"] = outcomes
        step["on_outcome"] = handlers

    def open_step(self, act: Act) -> dict[str, Any]:
        """Opening a page by its address, as the person did (another application, mostly)."""
        url = act.event.value or act.event.url or ""
        screen = self.screens.title_of(url)
        step_id = self.step_id(f"open_{screen}")
        same_app = origin(url) == origin(self.n.start_url)
        parts = urlsplit(url)
        address = parts.path + (f"?{parts.query}" if parts.query else "")
        address += f"#{parts.fragment}" if parts.fragment else ""
        step: dict[str, Any] = {
            "id": step_id,
            "intent": say(self.lang, "open", screen=screen),
            "action": "navigate",
            "value": (address or "/") if same_app else url,
        }
        state = self.screens.state_id(url)
        if state:
            step["expect"] = {"state": state}
        step["evidence"] = self.evidence([act.seq])
        self.step_events[step_id] = [act.seq]
        return step

    def open_by_data(self, steps: list[dict[str, Any]]) -> None:
        """An address the person typed that names one record (``/orders/48``) is opened by
        the value from the data that names it, or by a person: the recorded record for every
        row of the sheet would put each row's work into that one record."""
        names = {
            v: f"inputs.{n}"
            for v, n in self.placeholders.items()
            if n in self.inputs and shown.names_one(v)
        }
        for step in steps[1:]:  # the first: where the person began, a page of the application
            if step["action"] != "navigate":
                continue
            value, unexplained = fill_from(str(step["value"]), names)
            step["value"] = value
            if unexplained:
                step["executor"] = "human"
                parts = ", ".join(unexplained)
                self.note(
                    f"Krok „{step['intent']}”: adres {value} wskazuje jeden rekord ({parts}), a "
                    "nic w danych go nie wyznacza; otwiera go człowiek, dopóki nie wiadomo, "
                    "jak ten rekord znaleźć.",
                    f"Step “{step['intent']}”: the address {value} names one record ({parts}) "
                    "and nothing in the data says which; a person opens it until it is known "
                    "how to find that record.",
                )

    def read_copied(self, steps: list[dict[str, Any]], acts: list[Act]) -> list[dict[str, Any]]:
        """A value the person copied from a screen into a field (the account number from the
        VAT white list) is read on that screen and typed as read: it is no column of the
        sheet. Only a distinctive value counts, not typed before and not in the sheet, shown
        in one place with words of its own (``shown``)."""
        sheet = self.sheet_cells()
        by_seq = {seq: step for step in steps for seq in self.step_events.get(step["id"], [])}
        reads: dict[int, list[dict[str, Any]]] = {}
        read_as: dict[str, str] = {}
        """A value read on a screen -> the variable it was read into."""
        typed: set[str] = set()
        for index, act in enumerate(acts):
            value = shown.plain(act.event.value or "")
            step = by_seq.get(act.seq)
            name = self.only_use(steps, step, value) if act.kind in ("fill", "select") else None
            again = read_as.get(value.casefold())
            if step is not None and name is not None and again is not None:
                step["value"] = f"$vars.{again}"  # the same copied value in another field
                del self.inputs[name]
                continue
            found = (
                self.copied(act, acts[: index + 1], value, typed | sheet, name) if name else None
            )
            if found is None and step is not None and name is not None and act.kind == "select":
                found = self.option_named_before(act, acts[: index + 1], name)
                if found is not None:  # the customer the e-mail names, chosen by its words
                    step["match"] = "words"
            if found is None and step is not None and act.item:  # its input may type twice
                leads = self.item_leads(act, value)
                if leads:  # what the screen says of the field's item: the recordings choose
                    self.seen_after[str(step["id"])] = leads
            if found is not None and step is not None and name is not None:
                before, read = found
                step["value"] = f"$vars.{name}"  # the robot types what it read
                del self.inputs[name]
                read_as[value.casefold()] = name
                reads.setdefault(before, []).append(read)
            target = act.event.target
            clicked = (target.name or target.text) if target and target.row else None
            typed |= {shown.plain(v).casefold() for v in (value, clicked) if v}
        if not reads:
            return steps
        result: list[dict[str, Any]] = []
        for step in steps:
            for seq in self.step_events.get(step["id"], []):
                result += reads.pop(seq, [])
            result.append(step)
        return result

    def read_looked_up(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """What the person copied off a screen (Ctrl+C) and typed nowhere is what they came to
        look up (the customer's e-mail, the invoice's total): the robot reads it on that screen,
        right after the step that showed it, and hands it back (``RunResult.read``, the results
        sheet). A value typed in the recording is read for the field it goes into instead
        (``read_copied``); a copy whose place on the screen is not clear is left out, said."""
        typed = {
            shown.plain(a.event.value or "").casefold()
            for a in self.n.acts
            if a.kind in ("fill", "select") and a.event.value
        }
        position = {
            seq: index
            for index, step in enumerate(steps)
            for seq in self.step_events.get(step["id"], [])
        }
        names = set(self.inputs) | {str(s["save_as"]) for s in steps if s.get("save_as")}
        before: dict[int | None, list[dict[str, Any]]] = {}
        seen: set[str] = set()
        for act in self.n.acts:
            for copied in (o for o in act.observed if o.type == "copied"):
                value = shown.plain(copied.value or "")
                if not value or value.casefold() in typed or value.casefold() in seen:
                    continue
                seen.add(value.casefold())
                state = self.trace.state(copied.state_before) or self.trace.state(
                    copied.state_after
                )
                read = self.look_up(copied, value, state, names) if state is not None else None
                if read is None:
                    self.note(
                        f"Skopiowaną wartość „{value[:60]}” widać na ekranie w kilku miejscach "
                        "albo bez nazwy: robot jej nie odczytuje. Skopiuj ją tam, gdzie ma nazwę "
                        "(kolumna, pole, etykieta).",
                        f"The copied value “{value[:60]}” is shown in several places or without "
                        "a name: the robot does not read it. Copy it where it has a name (a "
                        "column, a field, a label).",
                    )
                    continue
                names.add(str(read["save_as"]))
                # before the first step done after the copy: the screen still shows it then
                at = min((i for seq, i in position.items() if seq > copied.seq), default=None)
                before.setdefault(at, []).append(read)
        if not before:
            return steps
        result: list[dict[str, Any]] = []
        for index, step in enumerate(steps):
            result += before.pop(index, [])
            result.append(step)
        return result + [r for reads in before.values() for r in reads]

    def look_up(
        self, copied: TraceEvent, value: str, state: TraceState, names: set[str]
    ) -> dict[str, Any] | None:
        """The read step of a copied value: its one place on the screen with words of its own
        (the copied element's column picks among cells), named after those words."""
        found = shown.places(state.aria, value)
        column = copied.target.column if copied.target is not None else None
        if column and any(p.kind == "cell" and p.label == column for p in found):
            found = [p for p in found if p.kind != "cell" or p.label == column]
        place = shown.best(found)
        if place is None and found:
            alone = shown.alone_on_screen(state.aria, found, value)
            place = alone[0] if len(alone) == 1 else None
        target = copied.target
        if (
            place is not None
            and place.kind == "cell"
            and target is not None
            and not (target.row is not None or target.column)
        ):  # copied off no table (a count „346 records found”): the cell with it is another
            place = None
        if place is None and found:
            if target is None or target.row is not None or target.column:
                return None  # named in several places: which one the person read is unclear
            # the recorder says which element was copied: read by its id, never by its place
            around = _words_around(state.aria, value) or "value"
            read = self.read_element(copied, value, state, unique(slug(around), names), around)
            if read is not None:
                read["evidence"] = self.evidence([copied.seq], self.copied_note(value))
                self.step_events[read["id"]] = [copied.seq]
            return read
        label = place.label if place is not None else _words_around(state.aria, value)
        base = slug(label or "") or "value"
        name, n = base, 1
        while name in names:
            n += 1
            name = f"{base}_{n}"
        if place is not None:
            # named after where it stood („Email”), not after the value copied that once
            read = self.read_step(Act(copied), place, state, copied.seq, name, place.label)
        else:
            read = self.read_element(copied, value, state, name, label or name)
        if read is not None:
            read["evidence"] = self.evidence([copied.seq], self.copied_note(value))
            self.step_events[read["id"]] = [copied.seq]
        return read

    def copied_note(self, value: str) -> str:
        return (
            f"Osoba skopiowała tu „{value[:60]}”: robot odczytuje tę wartość i ją oddaje"
            if self.lang == "pl"
            else f"The person copied “{value[:60]}” here: the robot reads it and hands it back"
        )

    def read_element(
        self, copied: TraceEvent, value: str, state: TraceState, name: str, label: str
    ) -> dict[str, Any] | None:
        """A copied value with no words of its own on the screen („6” of „6 records found”,
        a number in its own span): the element it was copied from, found by what does not
        change from record to record (its id, test id, field), never by where it stands among
        others nor by the value itself. None when the element has no such way."""
        target = copied.target
        if target is None or shown.plain(target.text or "") != value:
            return None
        ladder = [
            rung
            for rung in _locators(target, drop_row_css=False)
            if not (rung.get("css") and ":nth-" in str(rung["css"]))
            and not any(
                value.casefold() in str(rung.get(key) or "").casefold()
                for key in ("name", "text", "label", "css")
            )
        ]
        if not ladder:
            return None
        state_id = self.screens.state_id(state.url, state.window)
        screen = self.screens.title_of(state.url, state.window)
        return {
            "id": self.step_id(f"read_{name}"),
            "intent": say(self.lang, "read", field=label, screen=screen),
            "action": "read",
            "target": ladder,
            "save_as": name,
            **({"in_state": state_id} if state_id else {}),
        }

    def copied(
        self, act: Act, so_far: list[Act], value: str, known: set[str], name: str
    ) -> tuple[int, dict[str, Any]] | None:
        """Where the value typed by ``act`` had been shown: (the event to read it before, the
        read step); None when it was typed before, is in the sheet, or was not shown."""
        if act.event.secret or one_time_code(act) or not value:
            return None
        if value.casefold() in known:
            return None  # typed before (the same datum again), or a value of the sheet
        distinctive = shown.distinctive(value)
        here = _screen_key(act.event.url or "")
        for state, seq in self.screens_before(so_far):  # the closest that showed it first
            found = [
                p
                for p in shown.places(state.aria, value)
                if not (p.kind == "field" and p.label == act.field_name)  # the field itself
            ]
            if _screen_key(state.url) == here:
                # on the field's own screen a value may be its echo or a default; a message the
                # application showed before it was typed is neither (the failed check, p24)
                found = [p for p in found if p.kind == "words" and p.rest]
                if not found:
                    continue
            if not distinctive:  # "25": only right after the field's own name („Ilość: 25”)
                field_name = (act.field_name or "").casefold()
                found = [p for p in found if p.kind == "words" and p.label.casefold() == field_name]
            place = shown.best(found)
            if place is None and found:
                # several sentences say it: the one whose words stand once on the whole screen
                # (an inbox lists „Zamówienie PO-10007, …”; „zamówienia nr” is the e-mail's own)
                alone = shown.alone_on_screen(state.aria, found, value)
                place = alone[0] if len(alone) == 1 else None
            if place is None:
                if found:
                    return None  # shown in several places: which one the person read is unclear
                continue
            read = self.read_step(act, place, state, seq, name)
            words = [p for p in found if p.kind == "words"]
            if read is None and place.kind != "words" and len(words) == 1:
                # no value of the data names the cell's row: its sentence still says it
                read = self.read_step(act, words[0], state, seq, name)
            return (seq, read) if read is not None else None
        return None

    def item_leads(self, act: Act, value: str) -> list[str]:
        """The words the typed value follows in what the screen said of the field's item
        before it was typed („przyjechało” in „37241-E: przyjechało 20 szt.”); several when
        it follows several there (130 after „przyjechało” and after „rozdartych”)."""
        state = self.trace.state(act.event.state_before)
        if state is None or not act.item or not value:
            return []
        about = [
            " ".join(text.split())
            for node in parse_aria(state.aria).walk()
            for text in (node.name, node.value)
            if text and act.item in text
        ]
        token = re.compile(r"(?<![\w.,/-])" + re.escape(value) + r"(?![\w/-])")
        leads = set()
        for text in about:
            for match in token.finditer(text):
                clause = re.split(r"[;:,.]", text[: match.start()])[-1].split()
                if 1 <= len(clause) <= 4 and all(any(ch.isalpha() for ch in w) for w in clause):
                    leads.add(" ".join(clause))  # „przyjechało”, „zgniecionych lub rozdartych”
        return sorted(leads)

    def option_named_before(
        self, act: Act, so_far: list[Act], name: str
    ) -> tuple[int, dict[str, Any]] | None:
        """An option chosen because an earlier screen named it (benchmark p11: „Sklep
        internetowy Grądziel-Lew (K0013)” for the e-mail from „Dział zakupów, Sklep internetowy
        Grądziel-Lew”): (the event to read before, the read of the named area whose text holds
        every word of the option's name). The option's value itself was nowhere: no column of
        the sheet, not typed. None when no such area, or the name is one word."""
        label = act.event.option_label or ""
        wanted = options.words_of(options.option_name(label))
        if len(wanted) < 2:
            return None  # one word stands anywhere by chance
        here = (_screen_key(act.event.url or ""), act.event.window)
        for state, seq in self.screens_before(so_far):
            if (_screen_key(state.url), state.window) == here:
                continue  # the list's own screen shows every option
            root = parse_aria(state.aria)
            holders = [
                node
                for node in root.walk()
                if node.role in _AREAS
                and node.name
                and wanted <= options.words_of(f"{node.value or ''} {node.text()}")
            ]
            if not holders:
                continue
            area = min(holders, key=lambda node: len(node.value or "") + len(node.text()))
            state_id = self.screens.state_id(state.url, state.window)
            screen = self.screens.title_of(state.url, state.window)
            area_name = str(area.name)
            step_id = self.step_id(f"read_{area_name}")
            read: dict[str, Any] = {
                "id": step_id,
                "intent": say(self.lang, "read_area", area=area_name, screen=screen),
                "action": "read",
                "target": [{"role": area.role, "name": area_name}],
                "save_as": name,
                **({"in_state": state_id} if state_id else {}),
            }
            note = (
                f"Opcję „{label}” wskazuje tekst „{area_name}”: robot czyta ten tekst i wybiera "
                "opcję, której nazwę tekst wymienia"
                if self.lang == "pl"
                else f"The option “{label}” is named in “{area_name}”: the robot reads it and "
                "picks the option the text names"
            )
            read["evidence"] = self.evidence([seq], note)
            self.step_events[step_id] = [seq]
            return seq, read
        return None

    def screens_before(self, so_far: list[Act]) -> Iterator[tuple[TraceState, int]]:
        """The screens shown before the last of ``so_far``, the latest first, each with the
        event to read on it before: the screen each act was done on, and the one an act left
        when the person did nothing more there (read it, then typed another address:
        benchmark p20, the carrier's „Zgłoszono szkodę SZK/2026/0003.”)."""
        seen: set[str] = set()
        for position in range(len(so_far) - 1, -1, -1):
            earlier = so_far[position]
            shown_after: list[tuple[str | None, int]] = []
            if position + 1 < len(so_far):  # read it before the next act, while it is shown
                shown_after.append((earlier.event.state_after, so_far[position + 1].seq))
            for state_id, seq in [*shown_after, (earlier.event.state_before, earlier.seq)]:
                state = self.trace.state(state_id)
                if state is None or state.id in seen:
                    continue
                seen.add(state.id)
                yield state, seq

    def read_step(
        self,
        act: Act,
        place: shown.Place,
        state: TraceState,
        seq: int,
        name: str,
        label: str | None = None,
    ) -> dict[str, Any] | None:
        """Reading the value where it stood: by its term, its field or its column; a cell in
        the row named by a value from the data, or the only row."""
        within: dict[str, Any] | None = None
        target: list[dict[str, Any]] | None = None
        if place.kind == "words":
            pass  # read after its words, in the page or a frame of it (maptelo.sentences)
        elif place.kind == "term":
            target = [{"role": "definition", "column": place.label}]
        elif place.kind == "field":
            target = [{"role": place.role, "name": place.label}, {"label": place.label}]
        else:
            where = self.row_of(place)
            tables = _read_tables(place.table, state.aria)
            if where is None or not tables:
                return None
            target = [{"role": "cell", "column": place.label}]
            within = {"table": tables, "where": where}
        label = label or act.field_name or place.label
        value = act.event.value or ""
        state_id = self.screens.state_id(state.url, state.window)
        step_id = self.step_id(f"read_{label}")
        screen = self.screens.title_of(state.url, state.window)
        intent = (
            say(
                self.lang,
                "read_message" if place.rest else "read_words",
                words=place.lead,
                screen=screen,
            )
            if place.kind == "words"
            else say(self.lang, "read", field=place.label, screen=screen)
        )
        read: dict[str, Any] = {
            "id": step_id,
            "intent": intent,
            "action": "read",
            **(
                {"target": target}
                if target
                else (
                    {"after": place.lead, "rest": True}
                    if place.rest
                    else {"after": place.lead, "looks_like": sentences.shape(shown.plain(value))}
                )
            ),
            **({"within": within} if within else {}),
            "save_as": name,
            **({"in_state": state_id} if state_id else {}),
        }
        note = (
            f"Wartość wpisana w „{label}” stała wcześniej na ekranie „{screen}” "
            f"(„{place.label}”): robot ją tam odczytuje, nie bierze z arkusza"
            if self.lang == "pl"
            else f"The value typed into “{label}” was shown before on the “{screen}” screen "
            f"(“{place.label}”): the robot reads it there, not from the sheet"
        )
        read["evidence"] = self.evidence([seq], note)
        self.step_events[step_id] = [seq]
        return read

    def row_of(self, place: shown.Place) -> dict[str, Any] | None:
        """The row of a cell, named by a value from the data that only that row has; ``{}``
        for the only row; None when nothing names it."""
        if len(place.rows) == 1:
            return {}
        names = {v.casefold(): n for v, n in self.placeholders.items() if n in self.inputs}
        for column, text in place.row:
            name = names.get(shown.plain(text).casefold())
            if column == place.label or column.startswith("#") or name is None:
                continue
            same = [r for r in place.rows if dict(r).get(column) == text]
            if len(same) == 1:
                return {column: f"$inputs.{name}"}
        return None

    def only_use(
        self, steps: list[dict[str, Any]], step: dict[str, Any] | None, value: str
    ) -> str | None:
        """The input this step types, when nothing else uses it (else it stays a value from
        the data even if it was shown on a screen)."""
        reference = step.get("value") if step is not None else None
        if not (isinstance(reference, str) and reference.startswith("$inputs.")):
            return None
        name = reference.removeprefix("$inputs.")
        spec = self.inputs.get(name)
        if spec is None or spec.get("secret") or shown.plain(str(spec.get("example", ""))) != value:
            return None
        used = re.compile(rf"inputs\.{name}\b")
        uses = [s for s in steps if used.search(json.dumps(s, ensure_ascii=False))]
        return name if uses == [step] else None

    def sheet_cells(self) -> set[str]:
        """Every value of the sheet the person worked from (folded), when the recording kept it."""
        data, path = self.trace.header.data, self.trace.path
        if data is None or path is None:
            return set()
        try:
            table: Table = read_table(path.parent / data.file, data.sheet)
        except (TableError, OSError):
            return set()
        return {shown.plain(v).casefold() for row in table.rows for v in row.values() if v}

    def pick_step(self, act: Act) -> dict[str, Any]:
        """A date picked in a calendar: the date is a value from the data, the calendar is
        moved to it and its day clicked (``Calendar``)."""
        picked = act.picked
        assert picked is not None
        label = picked.label
        again = sum(1 for picked_label in self._picked_labels if picked_label == label)
        self._picked_labels.append(label)
        described = f"{label} ({again + 1})" if again else label  # a range: its second day
        name = (None if again else self.inputs_by_field.get(label)) or unique(
            slug(label), self._input_names
        )
        example = picked.day.isoformat()
        self.inputs[name] = {"type": "date", "description": described, "example": example}
        self.inputs_by_field[described] = name
        self.placeholders[example] = name
        calendar: dict[str, Any] = {"day": picked.pattern, "days": picked.days}
        if picked.month:
            calendar["month"] = picked.month
        for key, part in (
            ("box", picked.box),
            ("next", picked.next),
            ("previous", picked.previous),
        ):
            ladder = calendar_ladder(part, box=key == "box")
            if ladder:
                calendar[key] = ladder
        if not picked.opens:
            calendar["opens"] = False
        step_id = self.step_id(f"pick_{label}")
        target = (
            _locators(picked.target, drop_row_css=True)
            if picked.opens
            else calendar_ladder(picked.target, box=True)
        )
        step: dict[str, Any] = {
            "id": step_id,
            "intent": say(self.lang, "pick_date", field=described),
            "action": "pick_date",
            "target": target,
            "value": f"$inputs.{name}",
            "calendar": calendar,
        }
        in_state = self.screens.state_id(act.event.url, act.event.window)
        if in_state:
            step["in_state"] = in_state
        java = (act.event.url or "").startswith("java://")
        # a Java program's calendar over a field one cannot type into: no robot does it yet
        note = say(self.lang, "calendar_by_person") if java else None
        step["evidence"] = self.evidence(picked.seqs, note)
        if java:
            step["executor"] = "human"
        self.step_events[step_id] = picked.seqs
        return step

    def mark_control(self, act: Act, step: dict[str, Any], name: str) -> None:
        """A check a person makes before confirming (four eyes) is left to a person: ticking
        "zgodne z dokumentem", or approving what someone else asked for on a screen of
        requests (benchmark: control_automated). Done by the robot, the check would
        vanish while the trail says someone checked."""
        screen = act.event.url or ""
        if act.kind == "check" and _ATTESTS.search(f"{name} {act.field_name or ''}"):
            self._attested_on = screen
        elif not (
            act.kind == "click"
            and _APPROVES.search(name.strip())
            and (
                self._attested_on == screen
                or (_APPROVALS.search(self.screen_words(act)) and not self.confirms_own(act))
            )
        ):
            return
        step["control"] = True
        step["executor"] = "human"
        if self._control_noted != screen:  # one note for the check and its approval
            self._control_noted = screen
            self.note(
                f"Krok „{step['intent']}” to kontrola: osoba sprawdza dokument, zanim "
                "potwierdzi (cztery oczy). Robi go człowiek, a robot zatrzyma się przed nim. "
                "Jeśli firma pozwala robić to robotowi, odpowiedz na pytanie przy budowie "
                "modelu.",
                f"Step “{step['intent']}” is a check: a person compares with the document "
                "before confirming (four eyes). A person makes it, and the robot stops before "
                "it. If the company lets the robot make it, answer the question when the model "
                "is built.",
            )

    def only_opens_window(self, act: Act) -> bool:
        """A click that opened a window and sent nothing („Zapisz” opening „Zatwierdzenie
        zmian”, benchmark g039): the save is made in that window, not by this click (what a
        window sends is watched as anything else: a dry run lets nothing through)."""
        if self.sent_by(act):
            return False
        later = self.n.steps.index(act) + 1 if act in self.n.steps else len(self.n.steps)
        following = self.n.steps[later] if later < len(self.n.steps) else None
        after = self.trace.states.get(act.event.state_after or "")
        if after is not None and after.window > act.event.window:
            # unless it went away by itself and the person went on here: a progress window
            # („Importowanie…” after „Importuj zaznaczone”, benchmark M3) is no window the
            # save is made in
            return following is None or following.event.window > act.event.window
        # the person's next action is in a window over this one: this click brought it up
        # (its screen was not read when the person answered at once: benchmark D01)
        return following is not None and following.event.window > act.event.window

    def confirms_save(self, act: Act) -> bool:
        """The yes to a question the saving button before it asked („Zatwierdź”, then
        „Zatwierdzić notę?” and „Tak”): where a desktop program saves, which its recording
        cannot see in what was sent (benchmark D05, D01). Not a message's only OK, nor a no."""
        target = act.event.target
        if act.kind != "click" or target is None or not target.dialog or act not in self.n.steps:
            return False
        name = (target.name or target.text or "").strip()
        index = self.n.steps.index(act)
        if not name or _DISMISS.search(name) or index == 0:
            return False
        asked = self.n.steps[index - 1]
        before = asked.event.target
        words = f"{before.name or ''} {before.text or ''}" if before is not None else ""
        if asked.kind not in ("click", "press") or not _COMMIT_WORDS.search(words):
            return False
        if before is not None and before.dialog == target.dialog:
            return False  # the same window: not a question it brought up
        state = self.trace.state(act.event.state_before)
        root = parse_aria(state.aria) if state is not None else None
        window = root.find("dialog", target.dialog) if root is not None else None
        if root is None or window is None:  # its screen was not read (answered at once)
            return _YES.fullmatch(name) is not None  # a yes, never a message's OK
        scope = window if window.children else root  # a window of its own: its whole screen
        others = [n.name or "" for n in scope.walk() if n.role == "button" and n.name != name]
        return any(_DISMISS.search(other) for other in others)  # a question: yes or no

    def changed_nothing(self, act: Act) -> bool:
        """A click that sent nothing and went nowhere, in a recording that sees what is sent:
        „Usuń” on the filter of a list (Odoo's facet, benchmark p12) clears the filter and
        deletes nothing; its word does not make it a save. A delete asked to be confirmed is
        saved by the confirming click, which sends."""
        if act.kind != "click" or self.sent_by(act):
            return False
        if not any(event.sent for event in self.trace.events):
            return False  # a recording that does not see what is sent cannot say
        return not any(o.type in ("navigated", "downloaded") for o in act.observed)

    def mark_choice(self, act: Act, step: dict[str, Any], name: str) -> None:
        """A decision made where the screen offered another: „Akceptuj” clicked in an
        invoice's row that also has „Korekta (CN)” (benchmark M6), „Przyjmij reklamację” beside
        „Odrzuć reklamację” (p18). The recording shows which was chosen, never when the other
        is: a person makes the decision until the owner gives its rule, and an automation built
        from the map stops before it (one built from this recording accepted every invoice)."""
        target = act.event.target
        if act.kind != "click" or target is None:
            return
        if (target.dialog and _CONSENT.search(target.dialog)) or self.confirms_own(act):
            return  # a site's consents; the person's own changes confirmed (how it saves, g039)
        others = offered_choices(_screen_before(self.trace, act), target, name)
        if not others:
            return
        step["alternatives"] = others
        if step.get("executor", "deterministic") == "deterministic":
            step["executor"] = "human"
        table = target.row.table if target.row is not None else None
        if target.row is None:
            where_pl, where_en = "na ekranie", "the screen"
        elif table:
            where_pl, where_en = f"w wierszu tabeli „{table}”", f"the row of the table “{table}”"
        else:
            where_pl, where_en = "w wierszu tabeli", "the table's row"
        listed_pl = ", ".join(f"„{o}”" for o in others)
        listed_en = ", ".join(f"“{o}”" for o in others)
        self.note(
            f"Krok „{step['intent']}” to decyzja: wybrano „{name}”, a {where_pl} "
            f"{'jest' if len(others) == 1 else 'są'} też {listed_pl}. Nagranie nie mówi, kiedy "
            "wybrać inaczej, więc decyduje człowiek, a robot zatrzyma się przed tym krokiem. "
            f"Podaj regułę, kiedy wybierasz „{name}”, albo nagraj przypadek z inną decyzją.",
            f"Step “{step['intent']}” is a decision: “{name}” was chosen, and {where_en} also "
            f"offered {listed_en}. The recording does not say when to choose otherwise, so a "
            "person decides and the robot stops before the step. Give the rule for when "
            f"“{name}” is chosen, or record a case decided the other way.",
        )

    def confirms_own(self, act: Act) -> bool:
        """An approval in a window opened over the person's own changes („Zapisz” opens
        „Zatwierdzenie zmian”, where „Akceptuj” saves: benchmark g039) confirms those changes:
        no second person checks anything there, it is how this program saves."""
        if not act.event.window or act not in self.n.steps:
            return False
        earlier = self.n.steps[: self.n.steps.index(act)]
        typed = ("fill", "select", "check", "uncheck", "upload")
        return any(a.kind in typed and a.event.window < act.event.window for a in earlier)

    def screen_words(self, act: Act) -> str:
        """What the screen of an act says it is: its address, its title and headings."""
        state = self.trace.state(act.event.state_before)
        words = [act.event.url or "", act.event.title or ""]
        if state is not None:
            words += [n.name or "" for n in parse_aria(state.aria).find_all("heading")]
        return " ".join(unquote(w) for w in words)

    def build_step(self, act: Act, following: Act | None) -> dict[str, Any]:
        if act.calendar_unread:
            day = act.event.target.name if act.event.target else None
            self.note(
                f"Dnia „{day}” nie dało się odczytać jako daty z kalendarza (np. dwa miesiące "
                "dni bez nazw): krok klika ten sam dzień w każdym przebiegu. Wpisz datę w pole "
                "albo zmień ten krok.",
                f"The day “{day}” could not be read as a date of the calendar (two months of "
                "days without names, say): the step clicks the same day in every run. Type the "
                "date into the field instead, or change this step.",
            )
        if act.kind == "navigate":
            return self.open_step(act)
        if act.picked is not None:
            return self.pick_step(act)
        target = act.event.target
        assert target is not None or act.kind == "press"
        step: dict[str, Any] = {"action": {"select": "select_option"}.get(act.kind, act.kind)}
        label = act.field_name or (target.text if target else None) or "element"
        name = (target.name if target else None) or label
        seqs = [s for attempt in act.attempts for s in attempt.event_seqs] + [act.seq]
        evidence_note = None
        own_target: list[dict[str, Any]] | None = None
        if act.chosen is not None:
            input_name = self.input_for(act)
            step["action"] = "choose"
            step["value"] = f"$inputs.{input_name}"
            step["intent"] = say(self.lang, "choose", field=label)
            base = f"choose_{label}"
            seqs.append(act.chosen.seq)
        elif act.kind in ("fill", "select"):
            input_name = self.input_for(act)
            step["value"] = f"$inputs.{input_name}"
            key = "fill" if act.kind == "fill" else "select"
            step["intent"] = say(self.lang, key, field=label)
            if target is not None and target.row is not None and target.column:
                row = self.entry_row(act, target)
                if row is not None:
                    step["within"] = {
                        "table": _table_ladder(self.trace, act, target.row.table),
                        **row,
                    }
            if one_time_code(act):  # a robot cannot know it: the person types it
                step["executor"] = "human"
                self.note(
                    f"Krok „{step['intent']}”: kod jednorazowy (z aplikacji albo SMS) wpisuje "
                    "człowiek; robot zatrzyma się przed nim.",
                    f"Step “{step['intent']}”: a one-time code (from an app or a text message) "
                    "is typed by a person; the robot stops before it.",
                )
            base = f"{'enter' if act.kind == 'fill' else 'choose'}_{label}"
        elif act.kind == "upload":
            input_name = self.file_input(act, label)
            step["value"] = f"$inputs.{input_name}"
            step["intent"] = say(self.lang, "upload", field=label)
            base = f"upload_{label}"
        elif act.kind == "press":
            step["value"] = act.event.value or "Enter"
            step["intent"] = say(self.lang, "press", keys=step["value"])
            base = f"press_{step['value']}"
        elif act.kind in ("check", "uncheck"):
            by_data: tuple[str, str] | None = None
            if target is not None and target.row is not None and target.column:
                name = target.column
                known = self.data_in_row(act, target)
                named = self.row_named_by_data(act, target)
                where = (
                    {c: f"$inputs.{n}" for c, n in named.items()}
                    if named
                    else {known[0]: f"$inputs.{known[1]}"}
                    if known
                    else {}
                )
                if not where:
                    where, _ = _row_rule(self.trace, act)
                step["within"] = {
                    "table": _table_ladder(self.trace, act, target.row.table),
                    "where": where,
                }
                own_target = [{"role": "cell", "column": target.column}]
            elif (by_data := self.named_by_data(target)) is not None:
                # the option the record names (MiniWoB++ click-option: „Select Kelli”)
                column, input_name = by_data
                name = "{inputs." + input_name + "}"
                own_target = [{"role": (target.role if target else None) or "radio", "name": name}]
            step["intent"] = say(self.lang, act.kind, name=name)
            base = f"{act.kind}_{name}" if by_data is None else f"{act.kind}_{column}"
        elif (
            target is not None
            and target.row is not None
            and _clicked_value(target)
            and not _command_of_every_row(self.trace, act, target)
        ):
            assert target.column is not None
            value = (target.name or target.text or "").strip()
            table = _table_ladder(self.trace, act, target.row.table)
            named = None if self.from_data(value) else self.row_named_by_data(act, target)
            edge = None if self.from_data(value) or named else _sorted_edge(self.trace, act, target)
            if named:  # the record's own row: its customer and date, not the recorded number
                where = {column: f"$inputs.{name}" for column, name in named.items()}
                rule = " i " if self.lang == "pl" else " and "
                rule = rule.join(f"{column} = {{{name}}}" for column, name in named.items())
                step["intent"] = say(self.lang, "open_row_by", rule=rule)
            elif edge is not None:  # the newest (or oldest) of a sorted list, whichever it is
                where = {}
                step["intent"] = self.sorted_intent(edge, target)
            else:
                input_name = self.value_input(target.column, value)
                where = {target.column: f"$inputs.{input_name}"}
                step["intent"] = say(self.lang, "open_row", column=target.column, input=input_name)
            step["within"] = {"table": table, "where": where, **({"pick": edge} if edge else {})}
            own_target = [{"role": "cell", "column": target.column}]
            if target.role not in (None, "cell", "gridcell"):
                # the link in the cell: the cell's middle misses a link shorter than it (g017)
                own_target.insert(0, {"role": target.role, "column": target.column})
            base = f"open_{target.column}"
        elif (
            target is not None
            and target.row is not None
            and (target.role in ("link", "button") or (target.role in _NO_ROLE and target.text))
            and (named_link := self.link_named_by_data(act, target)) is not None
        ):  # the record's own value is the link (an e-mail by its subject in an inbox, p11)
            column, input_name = named_link
            mark = "{inputs." + input_name + "}"
            word = "click_link" if target.role == "link" else "click"
            step["intent"] = say(self.lang, word, name=mark)
            own_target = (
                [{"role": target.role, "name": mark}]
                if target.role not in _NO_ROLE
                else [{"text": mark}]  # the subject's words inside its link (Roundcube)
            )
            base = f"click_{column}"
        elif target is not None and target.row is not None and _picks_row(target):
            where, how = _row_rule(self.trace, act)
            rule = " i ".join(f"{k} = {v}" for k, v in where.items())
            known = self.data_in_row(act, target)
            named = self.row_named_by_data(act, target)
            if named is not None and (known is None or len(named) > 1):
                # the record's values the row shows: the employee and the day (Odoo, p13)
                column = next(iter(named))
                where, how = {c: f"$inputs.{n}" for c, n in named.items()}, "key"
                rule = " i ".join(f"{c} = {{{n}}}" for c, n in named.items())
            elif known is not None:  # the row the data names: searched for, or the sheet's
                column, input_name = known
                where, how = {column: f"$inputs.{input_name}"}, "key"
                rule = f"{column} = {{{input_name}}}"
            elif how in ("key", "all") and (place := _sorted_edge(self.trace, act, target)):
                # the first row of a list sorted by its date: the newest, whichever record that
                # is; its number is no value of the work (benchmark M5)
                where, how = {}, "sorted"
            elif how == "key":  # the record the work list names: its value is an input
                ((column, value),) = where.items()
                input_name = self.value_input(column, value)
                where = {column: f"$inputs.{input_name}"}
                rule = f"{column} = {{{input_name}}}"
            step["within"] = {
                "table": _table_ladder(self.trace, act, target.row.table),
                "where": where,
                **({"pick": place} if how == "sorted" else {}),
            }
            table_name = target.row.table or ""
            command = row_command(target)
            if how == "sorted":
                step["intent"] = self.sorted_intent(place, target)
            elif where and command:
                step["intent"] = say(
                    self.lang, "row_command", table=table_name, command=command, rule=rule
                )
            elif where:
                step["intent"] = say(self.lang, "row", table=table_name, rule=rule)
            elif command:  # nothing in the row has a header to name it by
                step["intent"] = say(
                    self.lang, "row_any_command", table=table_name, command=command
                )
            else:  # nothing in the row has a header to name it by (an inbox, a plain list)
                step["intent"] = say(self.lang, "row_any", table=table_name)
            base = f"pick_row_{target.row.table or 'table'}"
            if how == "sorted":
                evidence_note = (
                    "Wiersz wskazuje miejsce na posortowanej liście (pierwszy albo ostatni), "
                    "a nie numer z nagrania"
                    if self.lang == "pl"
                    else "The row is a place in a sorted list (the first or the last), not the "
                    "recorded number"
                )
            elif how == "key":
                evidence_note = (
                    f"Wiersz wskazuje wartość z danych wejściowych ({column}), "
                    "a nie stała z nagrania"
                    if self.lang == "pl"
                    else f"The row is identified by an input value ({column}), not a constant"
                )
            elif how == "rule":
                evidence_note = (
                    f"Regułę wyboru wiersza wywnioskowano z jednego nagrania: {rule}"
                    if self.lang == "pl"
                    else f"Row rule inferred from a single recording: {rule}"
                )
            else:
                evidence_note = (
                    "row identified by all its values"
                    if self.lang == "en"
                    else "Wiersz rozpoznany po wszystkich wartościach"
                )
            rows = _rows_before(self.trace, act, target.row.table)
            if not where and how != "sorted" and rows != 1:
                step["executor"] = "human"  # which row is the work, nothing on screen says
                self.note(
                    f"Krok „{step['intent']}”: nic w wierszu nie mówi, który wiersz wybrać "
                    "(kolumny bez nagłówków); wybiera człowiek, dopóki nie podasz reguły.",
                    f"Step “{step['intent']}”: nothing in the row says which row to pick "
                    "(columns without headers); a person picks it until a rule is given.",
                )
            elif how != "key":
                self.note(
                    f"Krok „{step['intent']}”: potwierdź regułę wyboru wiersza ({rule}) "
                    "albo nagraj więcej przebiegów.",
                    f"Step “{step['intent']}”: confirm the row rule ({rule}) or record more runs.",
                )
        elif (
            act.kind == "click"
            and target is not None
            and (target.role in _NAMED_BY_DATA or (target.role in _NO_ROLE and target.text))
            and (by_data := self.named_by_data(target)) is not None
        ):  # the record's own value names what is clicked (the button „Yes” the task names)
            column, input_name = by_data
            mark = "{inputs." + input_name + "}"
            word = "click_link" if target.role == "link" else "click"
            step["intent"] = say(self.lang, word, name=mark)
            own_target = (
                [{"text": mark}]
                if target.role in _NO_ROLE
                else [{"role": target.role, "name": mark}]
            )
            if target.dialog:  # only while its window is open, as any button of a window
                step["when"] = {"visible": {"role": "dialog", "name": target.dialog}}
            base = f"click_{column}"
        elif (
            act.kind == "click"
            and target is not None
            and target.row is None
            and target.item
            and (by_item := self.item_named_by_data(target)) is not None
        ):  # an e-mail of an inbox clicked at its subject: the record's sender in it names it
            column, input_name = by_item
            mark = "{inputs." + input_name + "}"
            step["intent"] = say(self.lang, "click", name=mark)
            own_target = [{"text": mark}]
            base = f"open_{column}"
        elif (
            act.kind == "click"
            and target is not None
            and (target.role in _NAMED_BY_DATA or (target.role in _NO_ROLE and target.text))
            and (in_part := self.named_in_part(target)) is not None
        ):  # a value of the record's row among its words („Tab #1”): asked unless proven
            column, input_name, marked = in_part
            word = "click_link" if target.role == "link" else "click"
            step["intent"] = say(self.lang, word, name=marked)
            own_target = (
                [{"text": marked}]
                if target.role in _NO_ROLE
                else [{"role": target.role, "name": marked}]
            )
            if target.dialog:
                step["when"] = {"visible": {"role": "dialog", "name": target.dialog}}
            base = f"click_{column}"
        elif target is not None and target.dialog:
            step["intent"] = say(self.lang, "dialog", dialog=human_title(target.dialog), name=name)
            dialog = target.dialog
            # only when that window is open: it may come only for some records ("Tak" when
            # the amount is high), and pressing a button that is not there is not the work
            step["when"] = {"visible": {"role": "dialog", "name": target.dialog}}
            base = dialog if name.lower() in dialog.lower() else f"{dialog}_{name}"
        else:
            role = target.role if target else None
            if role == "menuitem" and target is not None and target.column:  # an item in a menu
                step["intent"] = say(self.lang, "menu", menu=target.column, name=name)
            else:
                kind = "click_link" if role == "link" else "click"
                step["intent"] = say(self.lang, kind, name=name)
            base = f"click_{name}"
        if step["action"] == "click" and any(o.type == "downloaded" for o in act.observed):
            step["action"] = "download"  # the click gave a file: the robot keeps it
        if step["action"] == "click" and act.event.clicks == 2:
            step["clicks"] = 2  # a double click: a row of a list opens its record
            step["intent"] = say(self.lang, "double", what=step["intent"])
        if own_target is None and act.kind == "click" and target is not None:
            part = self.path_part(target)
            if part is not None:  # „Fawn” of „Linzy>Fawn”: the record's, never a constant
                step["executor"] = "human"
                self.note(
                    f"Krok „{step['intent']}”: klikany element to część wartości rekordu "
                    f"„{part}”, więc dla innego rekordu będzie inny. Robi go człowiek.",
                    f"Step “{step['intent']}”: what is clicked is a part of the record's value "
                    f"“{part}”, so another record clicks another one. A person does it.",
                )
        if own_target is not None:
            step["target"] = own_target
        elif target is not None:
            step["target"] = _locators(target, drop_row_css=target.row is not None)
            if "within" in step and _alone_in_row(self.trace, act, target):
                step["target"].append({"role": target.role})  # "the only link in the row"
            if not step["target"]:
                # nothing tells the element (no name, words or id): a robot cannot find it, so
                # a person does the step, and the model stays one a robot reads up to it
                step["target"] = [{"role": target.role} if target.role else {"css": target.tag}]
                step["executor"] = "human"
                self.note(
                    f"Krok „{step['intent']}”: element nie ma nazwy, słów ani identyfikatora, "
                    "więc robot go nie znajdzie i robi go człowiek. Nagraj go jeszcze raz albo "
                    "wskaż element w Studio.",
                    f"Step “{step['intent']}”: the element has no name, words or id, so a robot "
                    "cannot find it and a person does it. Record it again or point at the "
                    "element in Studio.",
                )
        words = f"{name} {label}"
        sends = (
            act.kind in ("click", "press")
            and _COMMIT_WORDS.search(words)
            and not _FILTER_WORDS.search(words)
            and not self.only_opens_window(act)
            and not self.changed_nothing(act)
        )
        no_undo = act.kind == "click" and not _DISMISS.search(words) and self.warned_no_undo(act)
        saves = sends or no_undo or self.sent_by(act) or self.confirms_save(act)
        if saves and target is not None and _CONSENT.search(target.dialog or ""):
            saves = False  # the site's consents answered: a dry run goes past it to the work
        if saves:  # "Księguj" saves too: it sent data; "Tak" to "Zatwierdzić notę?" too
            step["risk"] = "commit"
            if no_undo or _IRREVERSIBLE_WORDS.search(words):
                step["risk"] = "irreversible"  # an agent never does it without a person
        in_state = self.screens.state_id(act.event.url, act.event.window)
        if in_state:
            step["in_state"] = in_state
        self.mark_control(act, step, name)
        self.mark_choice(act, step, name)
        # a file given is the download's result (the robot waits for it): no screen to expect,
        # and the next button, there all along in a new tab, is none (benchmark M5)
        expect = None if step.get("action") == "download" else self.expectation(act, following)
        step_id = self.step_id(base)
        step = {"id": step_id, **step}
        self.outcomes_for(act, expect, step)
        step["evidence"] = self.evidence(seqs, evidence_note)
        self.step_events[step_id] = seqs
        return step

    def _landed(self, start_url: str) -> str:
        """Where the process really starts: after sign-in, or where the first page settled
        (a bookmark may be rewritten, e.g. Odoo turns #action=<name> into numbers)."""
        if start_url != self.trace.header.start_url:
            return start_url  # the address reached after signing in
        first = next((a for a in self.n.acts if a.kind == "navigate"), None)
        settled = self.trace.state(first.event.state_after) if first is not None else None
        return settled.url if settled is not None else start_url

    def build(self) -> MapResult:
        self.name_fields_by_data()
        steps: list[dict[str, Any]] = []
        start_url = self.n.start_url
        start = urlsplit(start_url)
        landed_url = self._landed(start_url)
        screen = self.screens.title_of(landed_url)
        open_id = self.step_id(f"open_{screen}")
        java = start.scheme == JAVA  # a program on the computer: it is opened, not an address
        open_step: dict[str, Any] = {
            "id": open_id,
            "intent": say(self.lang, "open_program", program=self.screens.app)
            if java
            else say(self.lang, "open", screen=screen),
            "action": "navigate",
            # the application's own address alone (http://erp:8000) is its first page: "/",
            # never an empty address in the SOP (the clean-Windows Lite test of 12.10)
            "value": (start.path or "/")
            + (f"?{start.query}" if start.query else "")
            + (f"#{start.fragment}" if start.fragment else ""),
        }
        start_state = self.screens.state_id(landed_url)
        if start_state:
            open_step["expect"] = {"state": start_state}
        first_seq = self.n.acts[0].seq if self.n.acts else 1
        open_step["evidence"] = self.evidence([first_seq])
        self.step_events[open_id] = [first_seq]
        steps.append(open_step)

        start_act = self.n.acts[0] if self.n.acts and self.n.acts[0].kind == "navigate" else None
        acts = [a for a in self.n.steps if a is not start_act]  # others: another application
        for index, act in enumerate(acts):
            following = acts[index + 1] if index + 1 < len(acts) else None
            steps.append(self.build_step(act, following))
        self.windows_and_dialogs(steps[1:], acts)
        steps = self.read_copied(steps, acts)
        steps = self.read_looked_up(steps)
        self.link_downloads(steps, acts)
        steps = self.each_rows(steps)
        steps = self.fold_lines(steps)
        self.open_by_data(steps)
        self.dialog_templates(steps)
        self.person_notes(steps)

        interrupts: list[dict[str, Any]] = []
        for act in self.n.by_role("interrupt"):
            target = act.event.target
            assert target is not None
            assert target.dialog is not None
            interrupt_id = slug(target.dialog)
            if any(i["id"] == interrupt_id for i in interrupts):
                continue
            interrupts.append(
                {
                    "id": interrupt_id,
                    "description": target.dialog,
                    "when": {"visible": {"role": "dialog", "name": target.dialog}},
                    "do": [{"action": "click", "target": _locators(target, drop_row_css=False)}],
                }
            )
            self.note(
                f"Okno „{target.dialog}” uznano za przerwanie "
                "(pojawiło się samo po wczytaniu strony).",
                f"The “{target.dialog}” dialog was treated as an interrupt "
                "(it appeared on its own).",
            )

        for act in self.n.by_role("noise"):
            target = act.event.target
            what = (target.name or target.text or target.label) if target is not None else None
            if act.kind == "click" and what:
                what = " ".join(what.split())[:60]
                self.note(
                    f"Kliknięcie w „{what}” pominięto: to nie przycisk ani pole, a nic się po nim "
                    "nie pojawiło. Jeśli było potrzebne, nagraj je jeszcze raz albo dopisz krok.",
                    f"The click on “{what}” was left out: it is no button or field, and nothing "
                    "appeared after it. If it was needed, record it again or add the step.",
                )

        preconditions = []
        if self.n.by_role("login"):
            preconditions.append(say(self.lang, "login", app=self.app))
        if self.inputs:
            self.note(
                "Wszystkie wprowadzone i wybrane wartości potraktowano jako dane wejściowe; "
                "rozpoznanie wartości stałych wymaga kilku nagrań.",
                "Every entered or selected value was treated as an input; "
                "identifying constants requires several recordings.",
            )

        records = self.bind_sources() if self.sheet else None
        started = written_date(self.trace.header.started_at.date(), self.lang)
        description = say(self.lang, "mapped_from", date=started)
        note = (self.trace.header.note or "").strip()
        if note:  # „Nowa cena do akceptacji” and „Mapę utworzono…” are two sentences
            description = f"{note}{'' if note[-1] in '.!?…' else '.'} {description}"
        data: dict[str, Any] = {
            "schema_version": "0.1",
            "id": self.process_id,
            "version": 1,
            "title": self.trace.header.title or self.process_id.replace("_", " ").capitalize(),
            "description": description,
            "application": {
                "name": self.app,
                "kind": "java" if start.scheme == "java" else "web",
                **({"window": self.trace.header.program} if self.trace.header.program else {}),
                "base_url": f"{start.scheme}://{start.netloc}",
                **({"timezone": self.trace.header.timezone} if self.trace.header.timezone else {}),
                **({"locale": self.trace.header.locale} if self.trace.header.locale else {}),
            },
            "preconditions": preconditions,
            "inputs": self.inputs,
            **({"records": records} if records else {}),
            "states": self.screens.states(self.typed_inputs()),
            "interrupts": interrupts,
            "exceptions": self.exceptions,
            "steps": steps,
        }
        if self.trace.header.private:
            keep_private(data)
        model = ProcessModel.model_validate(data)
        return MapResult(
            model=model,
            trace=self.trace,
            step_events=self.step_events,
            notes=self.notes,
            seen_after=self.seen_after,
        )


def _same_in_rows(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Two steps ticking (or unticking) the same box in two rows of one table, neither row
    named by the record's data (the record says which rows: no rule of rows)."""
    if a.get("action") != b.get("action") or a.get("action") not in ("check", "uncheck"):
        return False
    first, second = a.get("within"), b.get("within")
    if not first or not second or first.get("table") != second.get("table"):
        return False
    if a.get("target") != b.get("target") or a.get("when") or b.get("when"):
        return False
    one, other = first.get("where") or {}, second.get("where") or {}
    data = [v for v in (*one.values(), *other.values()) if isinstance(v, str) and "$" in v]
    return one != other and not data


def said_of(written: object) -> dict[str, Any]:
    """A step's description as written: why (its text), when it is done, whether a person
    decides there. Plain words are the why alone (as maps wrote them before)."""
    if isinstance(written, Mapping):
        return {
            "text": str(written.get("text") or "").strip(),
            "when": str(written.get("when") or "").strip(),
            "person": bool(written.get("person")),
        }
    return {"text": str(written or "").strip(), "when": "", "person": False}


def map_trace(
    trace: Trace,
    *,
    lang: Lang = "pl",
    process_id: str | None = None,
    notes: Mapping[int, str | Mapping[str, Any]] | None = None,
    sheet: bool = True,
) -> MapResult:
    """Turn one recording into a process model (plus what needs confirming). ``notes``: a
    step's description written on its map afterwards or while recording, by the number of an
    action of it (plain words: why; or why, when, whether a person decides). ``sheet``: the
    inputs take their columns from the sheet the recording names (its row is the work list's
    one row); False leaves them as typed, for a model of several recordings to decide where
    each comes from, and to ask when it is not sure."""
    return _Builder(normalize(trace), lang, process_id, notes, sheet).build()
