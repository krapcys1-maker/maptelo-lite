"""What each step did, as the recording saw it: the windows it opened and closed, the messages
it brought up, the fields the application filled by itself, the rows a table gained or lost,
the page it led to, the file it gave. Read from the screens before and after the step and from
what was observed after it, so that a document, and a model building an automation from it,
knows what a button does, not only that it was clicked."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from maptelo.mapping.naming import Lang
from maptelo.model.schema import ProcessModel
from maptelo.trace.aria import AriaNode, parse_aria, table_rows
from maptelo.trace.schema import Trace, TraceEvent, TraceState

EffectKind = Literal[
    "window", "opened", "closed", "message", "filled", "rows", "page", "download", "dialog", "note"
]

FIELD_ROLES = frozenset(
    {"textbox", "searchbox", "spinbutton", "combobox", "checkbox", "radio", "switch"}
)
MESSAGE_ROLES = frozenset({"alert", "status"})
WINDOW_ROLES = {
    True: frozenset({"dialog", "alertdialog", "region"}),
    False: frozenset({"dialog", "alertdialog"}),
}
"""Windows by the kind of application (java?): a Java program's frames are regions of its
window; a web page's regions are parts of the page, only its dialogs are windows."""


@dataclass(frozen=True)
class Effect:
    kind: EffectKind
    what: str
    """The window's title, the message, the field's name, the table, the address, the file."""
    value: str | None = None
    """The field's new value, the rows before and after ("2 → 3"), the dialog's answer."""

    def as_dict(self) -> dict[str, str]:
        out = {"kind": self.kind, "what": self.what}
        if self.value is not None:
            out["value"] = self.value
        return out


def model_effects(
    model: ProcessModel, sources: Mapping[str, tuple[Trace, Sequence[int]]]
) -> dict[str, list[Effect]]:
    """Step id -> what the step did in the recording it comes from (``sources`` as for the
    screenshots: the recording and the trace events of each step)."""
    java = model.application.kind == "java"
    out: dict[str, list[Effect]] = {}
    for step in model.steps:
        trace, seqs = sources.get(step.id, (None, ()))
        if trace is None or not seqs:
            continue
        names = {r.name for r in step.target or () if r.name} | {
            r.label for r in step.target or () if r.label
        }
        found = step_effects(trace, seqs, java=java, own=names)
        if found:
            out[step.id] = found
    return out


def step_effects(
    trace: Trace, seqs: Sequence[int], *, java: bool, own: Collection[str] = ()
) -> list[Effect]:
    """What the events ``seqs`` (one step) did: the screen when the person went on, compared
    with the screen before the step, and what was observed meanwhile. ``own``: the names of
    the step's element (its own field is filled by the person, not by the application)."""
    by_seq = {e.seq: e for e in trace.events}
    chosen = [by_seq[s] for s in seqs if s in by_seq]
    if not chosen:
        return []
    first, last = chosen[0], chosen[-1]
    later = [e for e in trace.events if e.seq > last.seq]
    following = next((e for e in later if e.is_action), None)
    meanwhile = [
        e for e in later if not e.is_action and (following is None or e.seq < following.seq)
    ]
    private = trace.header.private
    before = trace.state(first.state_before)
    after = trace.state(following.state_before) if following is not None else None
    after = after or trace.state(last.state_after)
    found: list[Effect] = []
    if before is not None and after is not None and first.type != "navigate":
        found += screen_changes(before, after, java=java, own=own, private=private)
    found += observed(meanwhile, private=private)
    return list(dict.fromkeys(found))


def screen_changes(
    before: TraceState,
    after: TraceState,
    *,
    java: bool,
    own: Collection[str] = (),
    private: bool = False,
) -> list[Effect]:
    old, new = parse_aria(before.aria), parse_aria(after.aria)
    if java:
        # a Java program's screen is the window worked in, not all of them: windows another
        # screen does not show were not closed. The window the work goes on in is the effect;
        # fields, messages and rows are compared within one window only
        if _path(before.url) != _path(after.url):
            return [Effect("window", _path(after.url).lstrip("/"))]
        found: list[Effect] = []
    else:
        roles = WINDOW_ROLES[java]
        was, now = _windows(old, roles), _windows(new, roles)
        found = [Effect("opened", title) for title in now if title not in was]
        found += [Effect("closed", title) for title in was if title not in now]
    said = set(_messages(old))
    found += [
        Effect("message", "" if private else text) for text in _messages(new) if text not in said
    ]
    old_fields, new_fields = _fields(old), _fields(new)
    for (role, name), value in new_fields.items():
        if name in own or (role, name) not in old_fields or old_fields[(role, name)] == value:
            continue
        found.append(Effect("filled", name, None if private else value))
    old_tables, new_tables = _tables(old), _tables(new)
    for name, count in new_tables.items():
        if name in old_tables and old_tables[name] != count:
            found.append(Effect("rows", name, f"{old_tables[name]} → {count}"))
    if not java and _path(before.url) != _path(after.url):
        found.append(Effect("page", _path(after.url)))
    return found


def observed(events: Sequence[TraceEvent], *, private: bool = False) -> list[Effect]:
    """What the recorder observed after a step: a page, a file, the browser's own question, an
    element that appeared (a window, a message), the person's note."""
    found: list[Effect] = []
    for event in events:
        if event.type == "navigated" and event.url:
            found.append(Effect("page", _path(event.url)))
        elif event.type == "downloaded":
            name = ", ".join(event.files) or (event.value or "")
            if name:
                found.append(Effect("download", name))
        elif event.type == "dialog" and event.dialog is not None:
            answer = "OK" if event.dialog.accepted else "Cancel"
            found.append(Effect("dialog", "" if private else event.dialog.message, answer))
        elif event.type == "appeared" and event.target is not None:
            target = event.target
            text = (target.name or target.text or "").strip()
            if target.role in ("dialog", "alertdialog") and text:
                found.append(Effect("opened", text))
            elif target.role in ("alert", "status") and text:
                found.append(Effect("message", "" if private else text))
        elif event.type == "note" and event.value:
            found.append(Effect("note", event.value))
    return found


def _windows(root: AriaNode, roles: Collection[str]) -> list[str]:
    return list(dict.fromkeys(n.name for n in root.walk() if n.role in roles and n.name))


def _messages(root: AriaNode) -> list[str]:
    texts = (" ".join(n.text().split()) for n in root.walk() if n.role in MESSAGE_ROLES)
    return list(dict.fromkeys(t for t in texts if t))


def _fields(root: AriaNode) -> dict[tuple[str, str], str]:
    """Named fields and their values; a name that two fields share says nothing of either."""
    seen: dict[tuple[str, str], str] = {}
    twice: set[tuple[str, str]] = set()
    for node in root.walk():
        if node.role not in FIELD_ROLES or not node.name:
            continue
        key = (node.role, node.name)
        if key in seen:
            twice.add(key)
        if node.role in ("checkbox", "radio", "switch"):
            seen[key] = "checked" if "checked" in node.attrs else ""
        else:
            seen[key] = node.value or ""
    return {k: v for k, v in seen.items() if k not in twice}


def _tables(root: AriaNode) -> dict[str, int]:
    """Named tables and how many of their rows show something (a block's empty rows do not)."""
    counts: dict[str, int] = {}
    for table in root.find_all("table"):
        if not table.name or table.name in counts:
            continue
        counts[table.name] = sum(
            1 for row in table_rows(table) if any(v.strip() for v in row.values())
        )
    return counts


def _path(address: str) -> str:
    parsed = urlparse(address)
    return (parsed.path.rstrip("/") or "/") + (f"?{parsed.query}" if parsed.query else "")


WORDS: dict[Lang, dict[EffectKind, str]] = {
    "pl": {
        "window": "dalej praca w oknie {what}",
        "opened": "otwiera się okno {what}",
        "closed": "zamyka się okno {what}",
        "message": "komunikat: {what}",
        "filled": "aplikacja sama wypełnia pole {what}: {value}",
        "rows": "tabela {what}: wiersze {value}",
        "page": "otwiera się strona {what}",
        "download": "pobiera się plik {what}",
        "dialog": "przeglądarka pyta: {what} (odpowiedź: {value})",
        "note": "osoba nagrywająca powiedziała: {what}",
    },
    "en": {
        "window": "the work goes on in the window {what}",
        "opened": "the window {what} opens",
        "closed": "the window {what} closes",
        "message": "message: {what}",
        "filled": "the application fills the field {what} by itself: {value}",
        "rows": "table {what}: rows {value}",
        "page": "the page {what} opens",
        "download": "the file {what} is downloaded",
        "dialog": "the browser asks: {what} (answer: {value})",
        "note": "the person recording said: {what}",
    },
}


def effect_text(effect: Effect, lang: Lang) -> str:
    """One effect in words: „Zapisz” → komunikat: „FRM-40400: …”."""

    def q(text: str) -> str:
        if not text:
            return "(…)"
        return f"„{text}”" if lang == "pl" else f"“{text}”"

    template = WORDS[lang][effect.kind]
    if effect.kind in ("rows", "page"):
        what = q(effect.what) if effect.kind == "rows" else effect.what
        return template.format(what=what, value=effect.value or "")
    value = (
        q(effect.value)
        if effect.kind == "filled" and effect.value is not None
        else (effect.value or "")
    )
    if effect.kind == "filled" and effect.value is None:
        template = template.split(":")[0]
    return template.format(what=q(effect.what), value=value)
