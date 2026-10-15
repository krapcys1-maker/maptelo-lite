"""Recording demonstrations in a browser driven by Playwright.

The recorder script reports actions and significant DOM changes; this module turns them
into trace records. After each burst of activity it waits until the page settles and
captures the screen state (accessibility snapshot, optionally a screenshot), so every
action knows the state before and after it.

Usage with a person at the keyboard: ``record_session``. Usage from a script (tests,
fixture generation): create a ``Recorder``, act on the page, call ``pump()`` after
each action, then ``stop()``.
"""

from __future__ import annotations

import contextlib
import queue
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Download, Frame, Page, Request, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from maptelo.browser import SANDBOX, AddressError, open_address, profile_context
from maptelo.capture.redact import redact_secrets
from maptelo.data.secrets import covered_copy
from maptelo.privacy import screenshot as take_screenshot
from maptelo.sends import describe, sends_data
from maptelo.trace.io import TraceWriter
from maptelo.trace.locators import candidates_for
from maptelo.trace.schema import (
    ACTION_TYPES,
    DataRef,
    DialogSeen,
    ElementInfo,
    TraceEnd,
    TraceEvent,
    TraceHeader,
    TraceState,
)
from maptelo.windows import latest_open

RECORDER_JS = (Path(__file__).with_name("recorder.js")).read_text(encoding="utf-8")
BINDING = "__mapteloEmit"
_PAGE_STATE = "() => window.__mapteloPageState ? window.__mapteloPageState() : null"


@dataclass(frozen=True)
class RecorderOptions:
    process: str | None = None
    title: str | None = None
    """The process as the person named it, when that is not its folder name."""
    note: str | None = None
    screenshots: bool = True
    allowed_origins: tuple[str, ...] = ()
    """Events from other origins are ignored. Empty: only the start URL's origin."""
    settle_ms: int = 300
    max_settle_ms: int = 5000
    data: Path | None = None
    """A table (.xlsx or .csv) the person takes values from: a copy goes with the recording,
    so building the model can tell which column each value came from."""
    sheet: str | None = None
    private: bool = False
    """Screens show personal or confidential data: screenshots cover what is typed and what
    tables hold, and the model built from the recording keeps no values as examples."""
    downloads: Path | None = None
    """Where files the page gives are kept for the person (None: their Downloads folder)."""


def _free_name(path: Path) -> Path:
    """``etykieta.pdf``, else ``etykieta (2).pdf``...: never over a file already there."""
    candidate, number = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        number += 1
    return candidate


_FRAME_LINE = re.compile(r"^(\s*)- iframe\b")


def _with_frames(page: Page, aria: str) -> str:
    """The screen with what its frames show: a page's snapshot says only "- iframe" for an
    e-mail shown in a frame (Roundcube), and a value copied out of it would have no place on
    any screen (benchmark p11). Matched to the frames shown, in order; a frame with a
    password field is left as it is, and so are all when they cannot be told apart."""
    lines = aria.split("\n")
    spots = [index for index, line in enumerate(lines) if _FRAME_LINE.match(line)]
    if not spots:
        return aria
    try:
        handles = [h for h in page.locator("iframe").element_handles() if h.is_visible()]
        frames = [h.content_frame() for h in handles]
    except PlaywrightError:
        return aria
    if len(frames) != len(spots):
        return aria  # which frame is which line is not certain
    for index, frame in reversed(list(zip(spots, frames, strict=True))):
        if frame is None:
            continue
        try:
            if frame.locator("input[type=password]").count():
                continue  # a sign-in in a frame: what it holds stays there
            frame.wait_for_load_state("load", timeout=2_000)
            inner = frame.locator("body").aria_snapshot(timeout=3_000)
        except PlaywrightError:
            continue
        match = _FRAME_LINE.match(lines[index])
        assert match is not None
        head = lines[index].rstrip()
        pad = match.group(1) + "  "
        lines[index : index + 1] = [
            head if head.endswith(":") else head + ":",
            *(pad + line for line in inner.split("\n") if line.strip()),
        ]
    return "\n".join(lines)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def new_recording_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(2)


class Recorder:
    def __init__(
        self, context: BrowserContext, out_dir: Path, options: RecorderOptions | None = None
    ) -> None:
        self.context = context
        self.out_dir = out_dir
        self.options = options or RecorderOptions()
        self.page: Page | None = None
        self._writer: TraceWriter | None = None
        self._queue: list[tuple[float, dict[str, Any]]] = []
        self._last_activity = 0.0
        self._t0 = 0.0
        self._seq = 0
        self._states = 0
        self._current_state: dict[int, str] = {}
        """Each window's last screen, by its place in ``windows``."""
        self._seen_page: dict[int, tuple[float, int]] = {}
        self._current_shot: dict[int, Path] = {}
        """Each window's last screen's picture, taken again when typing into a field stops."""
        self._typed_seen: dict[int, int] = {}
        """How much had been typed in each window's page when its picture was last taken."""
        self.windows: list[Page] = []
        """Every window of the recording, in the order they opened."""
        self._depths: list[int] = []
        """How deep each of ``windows`` is (maptelo.windows): what the recording says."""
        self._active = 0
        """The window the person worked in last: its screen is the one captured."""
        self._allowed: set[str] = set(self.options.allowed_origins)
        self._sent: list[tuple[float, str]] = []
        self._pending_downloads: list[Download] = []
        self._said: queue.SimpleQueue[tuple[float, str]] = queue.SimpleQueue()
        context.expose_binding(BINDING, self._on_emit)
        context.on("request", self._on_request)
        context.add_init_script(script=RECORDER_JS)

    @property
    def trace_path(self) -> Path:
        return self.out_dir / "trace.jsonl"

    @property
    def events(self) -> int:
        """Events written so far (what the person did, as recorded)."""
        return self._seq

    # --- lifecycle -------------------------------------------------------------------

    def start(self, url: str, page: Page | None = None) -> Page:
        self.page = page or self.context.new_page()
        self._allowed.add(_origin(url))
        self._t0 = time.time()
        self._writer = TraceWriter(self.trace_path)
        viewport = self.page.viewport_size
        timezone, locale = self._zone_and_language()
        self._writer.write(
            TraceHeader(
                recording_id=self.out_dir.name,
                process=self.options.process,
                title=self.options.title,
                note=self.options.note,
                started_at=datetime.now(UTC),
                start_url=url,
                browser=self.context.browser.version if self.context.browser else None,
                viewport=(viewport["width"], viewport["height"]) if viewport else None,
                timezone=timezone,
                locale=locale,
                data=self._keep_data(),
                private=self.options.private,
            )
        )
        self._follow(self.page)
        self.context.on("page", self._follow)  # a chooser, an approval, a print preview
        self._queue.append((time.time(), {"type": "navigate", "value": url, "url": url}))
        try:
            open_address(self.page, url)  # a portal that never ends loading is recorded too
        except AddressError:
            self._forget()
            raise
        with contextlib.suppress(PlaywrightError):
            self.page.bring_to_front()  # it opened behind Studio's window (the 11.10 test)
        self._install_in_open_documents()
        self._queue = [item for item in self._queue if item[1]["type"] != "navigated"]
        self.pump()
        return self.page

    def _forget(self) -> None:
        """Nothing was recorded (the start address cannot be reached): no recording is left
        behind to be listed as one, only a folder that held something else stays."""
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        self.trace_path.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            self.out_dir.rmdir()  # only when empty

    def note(self, text: str) -> None:
        """What the person says about what they are doing, from another thread (Studio's
        box): written with the time it was said, the map gives it to the step it came after."""
        if text.strip():
            self._said.put((time.time(), text.strip()))

    def _follow(self, page: Page) -> None:
        """Record in this window too: what the person does there and what it shows."""
        if page in self.windows:
            return
        depth = 0
        if self.windows:  # opened from a window of the recording, or from where one works
            opener = page.opener()
            below = self.windows.index(opener) if opener in self.windows else self._active
            depth = self._depths[below] + 1
        self.windows.append(page)
        self._depths.append(depth)
        window = len(self.windows) - 1
        page.on("framenavigated", lambda frame: self._on_navigated(frame, window))
        page.on("download", lambda download: self._on_download(download, window))
        page.on("domcontentloaded", lambda _: self._install(page))
        if window:  # a window the process opened: the person works there now
            self._active = window
            self._last_activity = time.monotonic()

    def _install(self, page: Page) -> None:
        """The recorder in a document just loaded. The init script is not enough: a window
        opened by window.open replaces its first, empty document with the page without running
        it again (benchmark g031: the chooser's search was lost). It installs once a document."""
        with contextlib.suppress(PlaywrightError):
            page.main_frame.evaluate(RECORDER_JS)

    def _window_of(self, page: Page | None) -> int:
        return self.windows.index(page) if page in self.windows else 0

    def _shown(self) -> tuple[int, Page]:
        """The window whose screen counts now: the one worked in last, while it is open;
        when it closed (a chooser, once something is chosen), the last one opened that is
        still open, where a run goes back to as well (maptelo.windows)."""
        assert self.page is not None
        if 0 < self._active < len(self.windows) and not self.windows[self._active].is_closed():
            return self._active, self.windows[self._active]
        self._active = latest_open(self.windows)
        if self._active == 0:
            return 0, self.page
        return self._active, self.windows[self._active]

    def _depth(self, window: int) -> int:
        return self._depths[window] if window < len(self._depths) else 0

    def _keep_data(self) -> DataRef | None:
        source = self.options.data
        if source is None:
            return None
        copy = self.out_dir / "data" / source.name
        covered_copy(source, copy)  # a password column does not go with the recording
        return DataRef(file=f"data/{source.name}", sheet=self.options.sheet)

    def _zone_and_language(self) -> tuple[str | None, str | None]:
        """Dates typed on screen mean local time: runs must use the same zone and language."""
        assert self.page is not None
        try:
            found = self.page.evaluate(
                "() => [Intl.DateTimeFormat().resolvedOptions().timeZone, navigator.language]"
            )
        except PlaywrightError:
            return None, None
        return (found[0] or None, found[1] or None) if isinstance(found, list) else (None, None)

    def _install_in_open_documents(self) -> None:
        """Single-page applications change screens without loading a new document, so the
        init script never runs again; put the recorder into what is open (it installs once)."""
        assert self.page is not None
        for frame in self.page.frames:
            with contextlib.suppress(PlaywrightError):
                frame.evaluate(RECORDER_JS)

    def stop(self, reason: str = "stopped") -> Path:
        if self._writer is None:
            raise RuntimeError("the recorder was not started")
        if self.page is not None and not self.page.is_closed():
            self.pump()
        else:
            self._keep_downloads()
            self._flush_without_state()
        end_reason = reason if reason in ("closed", "stopped", "timeout") else "stopped"
        self._writer.write(
            TraceEnd(
                t=round(time.time() - self._t0, 3),
                ended_at=datetime.now(UTC),
                reason=end_reason,
                events=self._seq,
                states=self._states,
            )
        )
        self._writer.close()
        return self.trace_path

    def wait_until_closed(
        self,
        poll_ms: int = 200,
        timeout_s: float | None = None,
        *,
        stop: Callable[[], bool] | None = None,
        progress: Callable[[int], None] | None = None,
    ) -> str:
        """Keep recording while a person works; returns why recording ended. ``stop`` ends it
        from outside (a button in Studio); ``progress`` hears how many events are written."""
        assert self.page is not None
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while True:
            if self.page.is_closed():
                return "closed"
            if stop is not None and stop():
                return "stopped"
            if deadline is not None and time.monotonic() > deadline:
                return "timeout"
            try:
                self.page.wait_for_timeout(poll_ms)
                if self.pump() and progress is not None:
                    progress(self._seq)
            except PlaywrightError:
                return "closed"

    # --- event intake (called by Playwright) -----------------------------------------

    def _on_emit(self, source: dict[str, Any], payload: dict[str, Any]) -> None:
        url = str(payload.get("url") or "")
        if url and _origin(url) not in self._allowed:
            return
        window = self._window_of(source.get("page"))
        payload["_window"] = window  # its place in self.windows; the trace gets its depth
        if payload.get("type") not in ("appeared", "navigated"):
            self._active = window  # where the person works now
        self._queue.append((float(payload.get("ts", time.time() * 1000)) / 1000, payload))
        self._last_activity = time.monotonic()

    def _on_request(self, request: Request) -> None:
        """Data the page sends to the application: what a save looks like on the wire."""
        if _origin(request.url) not in self._allowed:
            return
        if sends_data(request.method, request.url):
            sent = describe(request.method, request.url, private=self.options.private)
            self._sent.append((time.time(), sent))
            self._last_activity = time.monotonic()

    def _on_download(self, download: Download, window: int = 0) -> None:
        """A file the page gave: its name goes into the recording (a later upload of it is
        the same file); the file itself goes where the person's browser would put it."""
        page = self.windows[window] if window < len(self.windows) else self.page
        url = page.url if page is not None else None
        self._queue.append(
            (
                time.time(),
                {
                    "type": "downloaded",
                    "files": [download.suggested_filename],
                    "url": url,
                    "_window": window,
                },
            )
        )
        self._pending_downloads.append(download)
        self._last_activity = time.monotonic()

    def _keep_downloads(self) -> None:
        """Save what the page gave into the person's Downloads folder: during a recording
        the browser holds it in a temporary folder, where nobody would find it to upload."""
        pending, self._pending_downloads = self._pending_downloads, []
        folder = self.options.downloads or Path.home() / "Downloads"
        for download in pending:
            if not folder.is_dir():
                continue
            target = _free_name(folder / download.suggested_filename)
            with contextlib.suppress(PlaywrightError, OSError):
                download.save_as(target)

    def _on_navigated(self, frame: Frame, window: int = 0) -> None:
        page = self.windows[window] if window < len(self.windows) else self.page
        is_main = page is not None and frame == page.main_frame
        if is_main and _origin(frame.url) in self._allowed:
            self._queue.append(
                (time.time(), {"type": "navigated", "url": frame.url, "_window": window})
            )
            self._last_activity = time.monotonic()

    # --- processing --------------------------------------------------------------------

    def pump(self) -> int:
        """Write pending events once the page has settled; returns how many were written."""
        page = self.page
        if page is None or self._writer is None or page.is_closed():
            return 0
        self._keep_downloads()
        while True:  # what the person said meanwhile (Studio's box, another thread)
            try:
                said_at, text = self._said.get_nowait()
            except queue.Empty:
                break
            self._queue.append((said_at, {"type": "note", "value": text, "_window": self._active}))
        changed = self._page_changed()  # what the page still sent arrives meanwhile (a press
        # taken for the click a moment after the release): asked before the queue is looked at
        if not self._queue and not changed:
            self._retake_after_typing()
            return 0
        page_info = self._settle()
        batch, self._queue = sorted(self._queue, key=lambda item: item[0]), []
        sent, self._sent = self._sent, []
        window, _ = self._shown()
        state = self._capture_state(page_info)
        written = 0
        owners = _senders(batch, sent)
        for index, (ts, payload) in enumerate(batch):
            event = self._event(ts, payload, state.id if state else None, owners.get(index, []))
            if event is not None:
                self._writer.write(event)
                written += 1
        if state is not None:
            self._writer.write(state)
            self._current_state[window] = state.id
            if state.screenshot is not None:
                self._current_shot[window] = self.out_dir / state.screenshot
            else:
                self._current_shot.pop(window, None)
        return written

    def _retake_after_typing(self) -> None:
        """The current screen's picture again once the person stopped typing into a field.
        What is typed reaches the trace only when the field is left, with the click on „Save”,
        so the screen before that click showed the form without it (the Lite film of 13.10:
        „Click “Save”” with an empty date). Only the picture: the snapshot keeps what the
        screen held when it was read, and every event of that screen comes after the typing."""
        if not self.options.screenshots:
            return
        info = self._page_info()
        window, page = self._shown()
        shot = self._current_shot.get(window)
        if info is None or shot is None:
            return
        typed = int(info.get("typed") or 0)
        if typed == self._typed_seen.get(window, 0):
            return
        if float(info.get("typedQuietMs") or 0) < self.options.settle_ms:
            return  # still typing
        try:
            take_screenshot(page, shot, private=self.options.private, type="jpeg", quality=60)
        except PlaywrightError:
            return
        self._typed_seen[window] = typed

    def _page_changed(self) -> bool:
        info = self._page_info()
        if info is None:
            return False
        window, _ = self._shown()
        return (info["document"], info["significant"]) != self._seen_page.get(window)

    def _page_info(self) -> dict[str, Any] | None:
        _, page = self._shown()
        try:
            info = page.evaluate(_PAGE_STATE)
        except PlaywrightError:
            return None
        return info if isinstance(info, dict) else None

    def _settle(self) -> dict[str, Any] | None:
        assert self.page is not None
        deadline = time.monotonic() + self.options.max_settle_ms / 1000
        settle_s = self.options.settle_ms / 1000
        info = None
        while time.monotonic() < deadline:
            info = self._page_info()
            idle = time.monotonic() - self._last_activity >= settle_s
            if (
                info is not None
                and idle
                and info["ready"] == "complete"
                and info["quietMs"] >= self.options.settle_ms
            ):
                return info
            try:
                self._shown()[1].wait_for_timeout(50)
            except PlaywrightError:
                return None
        return info

    def _capture_state(self, info: dict[str, Any] | None) -> TraceState | None:
        window, page = self._shown()
        try:
            aria = page.locator("body").aria_snapshot(timeout=5000)
            title = page.title()
        except PlaywrightError:
            return None
        aria = _with_frames(page, aria)
        info = self._page_info() or info
        aria = redact_secrets(aria, info["passwords"] if info else [])
        self._states += 1
        state_id = f"s{self._states:04d}"
        screenshot = None
        if self.options.screenshots:
            screenshot = f"screens/{state_id}.jpg"
            try:
                (self.out_dir / "screens").mkdir(parents=True, exist_ok=True)
                take_screenshot(
                    page,
                    self.out_dir / screenshot,
                    private=self.options.private,
                    type="jpeg",
                    quality=60,
                )
            except PlaywrightError:
                screenshot = None
        if info is not None:
            self._seen_page[window] = (info["document"], info["significant"])
            self._typed_seen[window] = int(info.get("typed") or 0)
        return TraceState(
            id=state_id,
            t=round(time.time() - self._t0, 3),
            url=page.url,
            title=title,
            aria=aria,
            screenshot=screenshot,
            window=self._depth(window),
        )

    def _event(
        self,
        ts: float,
        payload: dict[str, Any],
        state_after: str | None,
        sent: list[str] | None = None,
    ) -> TraceEvent:
        kind = str(payload["type"])
        target = None
        if payload.get("target"):
            target = ElementInfo.model_validate(payload["target"])
            target.candidates = candidates_for(target)
            if target.calendar is not None:  # the arrows, the calendar and its field too
                seen = target.calendar
                for around in [*seen.controls, seen.box, seen.field]:
                    if around is not None:
                        around.candidates = candidates_for(around)
        secret = bool(payload.get("secret"))
        window = int(payload.get("_window") or 0)
        dialog = payload.get("dialog")
        self._seq += 1
        return TraceEvent(
            seq=self._seq,
            t=round(max(ts - self._t0, 0.0), 3),
            type=kind,
            url=payload.get("url"),
            title=payload.get("title"),
            target=target,
            value=None if secret else payload.get("value"),
            option_label=payload.get("option_label"),
            secret=secret,
            secret_no=int(payload["secret_no"]) if secret and payload.get("secret_no") else None,
            files=[str(name) for name in payload.get("files") or []],
            sent=sent or [],
            dialog=DialogSeen.model_validate(dialog) if dialog else None,
            window=self._depth(window),
            state_before=self._current_state.get(window, self._current_state.get(0)),
            state_after=state_after,
        )

    def _flush_without_state(self) -> None:
        if self._writer is None:
            return
        for ts, payload in sorted(self._queue, key=lambda item: item[0]):
            self._writer.write(self._event(ts, payload, None))
        self._queue = []


def _senders(
    batch: list[tuple[float, dict[str, Any]]], sent: list[tuple[float, str]]
) -> dict[int, list[str]]:
    """Which action set off each request that sent data: the last one done before it. A
    request before any action of the batch (a timer, a page loading) belongs to none."""
    owners: dict[int, list[str]] = {}
    actions = [i for i, (_, payload) in enumerate(batch) if payload.get("type") in ACTION_TYPES]
    for ts, what in sent:
        before = [i for i in actions if batch[i][0] <= ts]
        if before and what not in owners.setdefault(before[-1], []):
            owners[before[-1]].append(what)
    return owners


def record_session(
    url: str,
    out_dir: Path,
    options: RecorderOptions | None = None,
    *,
    channel: str | None = None,
    headless: bool = False,
    video: bool = False,
    timeout_s: float | None = None,
    profile: Path | None = None,
    storage_state: Path | None = None,
    stop: Callable[[], bool] | None = None,
    progress: Callable[[int], None] | None = None,
    on_open: Callable[[], None] | None = None,
    listen: Callable[[Callable[[str], None]], None] | None = None,
) -> Path:
    """Open a browser, record until the person closes it, and return the trace path.
    With ``profile`` it is the person's own browser profile, signed in already; with
    ``storage_state`` a saved sign-in instead. ``on_open`` hears when the start page is open
    (Studio brings the browser's window in front then); ``listen`` is given the recorder's ear
    for what the person says about what they are doing (Studio's box)."""
    with sync_playwright() as playwright, contextlib.ExitStack() as opened:
        window: dict[str, Any] = {
            "viewport": {"width": 1280, "height": 860},
            "record_video_dir": str(out_dir / "video") if video else None,
        }
        browser = None
        if profile is not None:
            context = opened.enter_context(
                profile_context(playwright, profile, headless=headless, channel=channel, **window)
            )
        else:
            browser = playwright.chromium.launch(
                headless=headless, channel=channel, chromium_sandbox=SANDBOX
            )
            context = browser.new_context(
                storage_state=str(storage_state) if storage_state else None, **window
            )
        recorder = Recorder(context, out_dir, options)
        recorder.start(url, context.pages[0] if context.pages else None)
        if listen is not None:
            listen(recorder.note)
        if on_open is not None:
            on_open()
        try:
            reason = recorder.wait_until_closed(timeout_s=timeout_s, stop=stop, progress=progress)
        except KeyboardInterrupt:
            reason = "stopped"
        path = recorder.stop(reason)
        for closable in (context, browser):
            if closable is not None:
                with contextlib.suppress(PlaywrightError):  # the person already closed it
                    closable.close()
        return path
