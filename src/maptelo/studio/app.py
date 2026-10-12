"""Maptelo Studio: a page for the person at this computer, and nobody else.

It listens on 127.0.0.1 only. The address it opens carries a one-time key that the page
keeps as a cookie (SameSite=Strict, so other sites cannot use it); every request for data
must carry it, a request must name this computer as its host (a site cannot rebind its
name to 127.0.0.1 and read the answers), and a request that changes something must carry
a header no other site can send without asking first. Files are served only from the
workspace.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from maptelo import __version__, environment
from maptelo.checks import summary_line
from maptelo.data import sheet_names
from maptelo.data.tables import TableError
from maptelo.mapping.naming import Lang
from maptelo.studio import readiness, recording
from maptelo.studio.common import RunProblemError, keep_page_language, page_language
from maptelo.studio.jobs import BusyError, Jobs
from maptelo.studio.polish import polish, polish_all
from maptelo.studio.workspace import Workspace

COOKIE = "maptelo_studio"
LOCAL = {"127.0.0.1", "localhost", "[::1]"}
STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 50 * 1024 * 1024
WRITES = {"commit", "irreversible"}
WORKSPACE_FILE = {
    "Cache-Control": "no-cache",
    "Content-Security-Policy": "sandbox allow-scripts allow-popups allow-downloads",
    "X-Content-Type-Options": "nosniff",
}
"""How a workspace file is served: checked again each time, and a page among them opens as a
sandbox, apart from Studio's origin, its key and its API."""


class _NotFoundError(Exception):
    pass


class _BadRequestError(Exception):
    pass


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except (ValueError, UnicodeError) as exc:
        raise _BadRequestError("Niepoprawny JSON w żądaniu.") from exc
    if not isinstance(value, dict):
        raise _BadRequestError("Żądanie musi zawierać obiekt JSON.")
    return value


class _Fresh(StaticFiles):
    """The page's own files, checked again on every load: after an update nobody keeps
    working with the previous version of the page."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _hostname(host: str) -> str:
    if host.startswith("["):
        return host[: host.find("]") + 1]
    return host.split(":", 1)[0]


class Guard:
    """Only this computer, only with the key, and changes only from Studio's own page."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if _hostname(headers.get("host", "")) not in LOCAL:
            await JSONResponse({"error": "Studio odpowiada tylko na tym komputerze."}, 403)(
                scope, receive, send
            )
            return
        if scope["path"].startswith("/api/"):
            given = Request(scope).cookies.get(COOKIE) or headers.get("x-maptelo-token", "")
            if not secrets.compare_digest(given.encode(), self.token.encode()):
                message = "Open Studio from the address it showed when it started."
                await JSONResponse({"error": message}, 401)(scope, receive, send)
                return
            if scope["method"] not in ("GET", "HEAD") and headers.get("x-maptelo") != "1":
                await JSONResponse({"error": "Zmiany przychodzą tylko ze strony Studio."}, 403)(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)


def _lang(request: Request) -> Lang:
    """The page's language: Polish, unless it asks for English (Maptelo Lite's page can)."""
    return "en" if request.headers.get("x-maptelo-lang") == "en" else "pl"


def _said(text: str, lang: Lang) -> str:
    """What the core says (in English), in the page's language."""
    return text if lang == "en" else polish(text)


def _problems(problems: list[str], status: int = 400, lang: Lang = "pl") -> JSONResponse:
    return JSONResponse({"problems": problems if lang == "en" else polish_all(problems)}, status)


LITE_WORDS = [
    ("can be recorded and run", "can be recorded"),
    ("można nagrywać i uruchamiać", "można nagrywać"),
    ("Studio", "Maptelo Lite"),
]
"""What the look at this computer says of Studio and of runs, as Maptelo Lite (it records)."""


def _as_lite(text: str) -> str:
    for full, lite in LITE_WORDS:
        text = text.replace(full, lite)
    return text


def _busy(exc: BusyError, lang: Lang) -> str:
    """One job at a time: the one still going."""
    return (
        f"Finish first: {exc.job.title}" if lang == "en" else f"Najpierw zakończ: {exc.job.title}"
    )


def _open_with_system(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


ROBOT_ONLY = "the full Maptelo runs processes: Maptelo Lite only maps them"
"""What Lite says to a request for the robot (a run, a model of several demonstrations, its
questions and repairs, shadow mode, agents): its page does not offer them."""


ROBOT_REQUESTS = [
    ("/api/runs", "POST"),
    ("/api/shadow", "POST"),
    ("/api/build", "POST"),
    ("/api/processes/{key}/questions", "POST"),
    ("/api/processes/{key}/repairs/accept", "POST"),
    ("/api/doctor", "POST"),
    ("/api/agents/config", "POST"),
    ("/api/agents/try", "POST"),
    ("/api/point", "POST"),
]
"""The robot's requests that Lite answers with ``ROBOT_ONLY`` (its page offers none of them)."""


def create_app(
    workspace: Workspace,
    token: str,
    jobs: Jobs | None = None,
    opener: Callable[[Path], None] = _open_with_system,
    *,
    lite: bool = False,
) -> Starlette:
    """Studio's server. ``lite``: Maptelo Lite, which records and maps one demonstration at a
    time (its steps, SOP, BPMN, report) and has no robot."""
    jobs = jobs or Jobs()
    # The browser the forms offer first: the one IT's policy names (then it is the only one),
    # else one this computer has and no policy forbids driving.
    browser = environment.recommended_browser()
    required = environment.required_browser()

    async def index(request: Request) -> Response:
        given = request.query_params.get("t")
        if given is not None:
            response = RedirectResponse("/", status_code=303)
            if secrets.compare_digest(given.encode(), token.encode()):
                response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/")
            return response
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    def state(request: Request) -> JSONResponse:
        current = jobs.current
        return JSONResponse(
            {
                "version": __version__,
                "workspace": str(workspace.root),
                "job": current.view(None) if current else None,
                "browser": browser,
                "browser_required": required is not None,
                "lite": lite,
                "lang": page_language() if lite else "pl",  # the full Studio speaks Polish
            }
        )

    async def language(request: Request) -> JSONResponse:
        chosen = (await _json_object(request)).get("lang")
        if chosen not in ("pl", "en"):
            return _problems(["the language is pl or en"], lang=_lang(request))
        keep_page_language("en" if chosen == "en" else "pl")
        return JSONResponse({"lang": chosen})

    def this_computer(request: Request) -> JSONResponse:
        lang = _lang(request)
        checks = environment.probe(workspace.root, lang=lang)
        shown = [asdict(c) for c in checks]
        for check in shown if lite else []:
            for field in ("detail", "hint"):
                if isinstance(check.get(field), str):
                    check[field] = _as_lite(check[field])
        return JSONResponse(
            {
                "checks": shown,
                "summary": summary_line(checks, lang),
                "ready": not any(c.verdict == "FAIL" for c in checks),
                "browser": environment.recommended_browser(),
            }
        )

    async def upload(request: Request) -> JSONResponse:
        lang = _lang(request)
        name = request.query_params.get("name", "")
        body = await request.body()
        if not body:
            return _problems(["the file is empty"], lang=lang)
        if len(body) > MAX_UPLOAD:
            return _problems(["the file is larger than 50 MB"], 413, lang)
        try:
            path = workspace.keep_sheet(name, body)
        except (ValueError, TableError) as exc:
            return _problems([str(exc)], lang=lang)
        return JSONResponse({"sheet": workspace.relative(path), "sheets": sheet_names(path)})

    def job(request: Request) -> JSONResponse:
        try:
            found = jobs.get(request.path_params["job"])
        except KeyError:
            raise _NotFoundError("there is no such job") from None
        after = request.query_params.get("after", "0")
        view = found.view(int(after) if after.isdigit() else 0)
        if view.get("error"):
            view["error"] = _said(view["error"], _lang(request))
        return JSONResponse(view)

    def stop(request: Request) -> JSONResponse:
        try:
            found = jobs.get(request.path_params["job"])
        except KeyError:
            raise _NotFoundError("there is no such job") from None
        found.stop_requested = True
        return JSONResponse(found.view(0))

    def file(request: Request) -> Response:
        try:
            path = workspace.inside(request.path_params["path"])
        except PermissionError as exc:
            return JSONResponse({"error": _said(str(exc), _lang(request))}, 403)
        if not path.is_file():
            raise _NotFoundError("there is no such file")
        # A map made again keeps its file names: checked every time, never an old SOP or
        # picture. A page from the workspace (a report) opens apart from Studio and its key.
        return FileResponse(path, headers=WORKSPACE_FILE)

    async def open_path(request: Request) -> JSONResponse:
        data = await _json_object(request)
        try:
            path = workspace.inside(str(data.get("path", "")))
        except PermissionError as exc:
            return JSONResponse({"error": _said(str(exc), _lang(request))}, 403)
        if not path.exists():
            raise _NotFoundError("there is no such file or folder")
        opener(path)
        return JSONResponse({"opened": workspace.relative(path)})

    def drafts(request: Request) -> JSONResponse:
        return JSONResponse(
            [
                {
                    "process": key,
                    "title": recording.process_title(workspace, key),
                    "recordings": len(workspace.recording_folders(key)),
                }
                for key in workspace.drafts()
            ]
        )

    def recordings(request: Request) -> JSONResponse:
        return JSONResponse(recording.recordings_view(workspace, request.path_params["key"]))

    async def start_recording(request: Request) -> JSONResponse:
        lang = _lang(request)
        try:
            wanted = recording.RecordRequest.from_json(await _json_object(request))
            work = recording.record_work(workspace, wanted)
        except RunProblemError as exc:
            return _problems(exc.problems, lang=lang)
        try:
            named = wanted.title or wanted.process  # as the person named it
            title = f"Recording: {named}" if lang == "en" else f"Pokaz: {named}"
            job = jobs.start("record", title, work, process=wanted.process)
        except BusyError as exc:
            return _problems([_busy(exc, lang)], 409, lang)
        return JSONResponse(job.view(), 202)

    def java_windows(request: Request) -> JSONResponse:
        return JSONResponse(recording.java_programs(_lang(request)))

    async def make_map(request: Request) -> JSONResponse:
        data = await _json_object(request)
        try:
            made = recording.map_recording(
                workspace,
                str(data.get("process", "")),
                str(data.get("recording", "")),
                str(data.get("lang") or _lang(request)),
            )
        except RunProblemError as exc:
            return _problems(exc.problems)
        return JSONResponse(made)

    def profiles(request: Request) -> JSONResponse:
        return JSONResponse(readiness.profiles_view())

    async def sign_in(request: Request) -> JSONResponse:
        lang = _lang(request)
        try:
            wanted = readiness.SignInRequest.from_json(await _json_object(request))
            work = readiness.sign_in_work(wanted)
        except RunProblemError as exc:
            return _problems(exc.problems, lang=lang)
        try:
            profile = wanted.profile
            title = (
                f"Sign-in: profile {profile}" if lang == "en" else f"Logowanie: profil {profile}"
            )
            job = jobs.start("sign-in", title, work)
        except BusyError as exc:
            return _problems([_busy(exc, lang)], 409, lang)
        return JSONResponse(job.view(), 202)

    async def not_found(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"error": _said(str(exc), _lang(request))}, 404)

    async def robot_only(request: Request) -> JSONResponse:
        return _problems([ROBOT_ONLY], 404, _lang(request))

    routes: list[BaseRoute] = [
        Route("/", index),
        Route("/api/state", state),
        Route("/api/language", language, methods=["POST"]),
        Route("/api/environment", this_computer),
        Route("/api/sheets", upload, methods=["POST"]),
        Route("/api/jobs/{job}", job),
        Route("/api/jobs/{job}/stop", stop, methods=["POST"]),
        Route("/api/files/{path:path}", file),
        Route("/api/open", open_path, methods=["POST"]),
        Route("/api/drafts", drafts),
        Route("/api/recordings", start_recording, methods=["POST"]),
        Route("/api/recordings/{key}", recordings),
        Route("/api/java/windows", java_windows),
        Route("/api/maps", make_map, methods=["POST"]),
        Route("/api/profiles", profiles, methods=["GET"]),
        Route("/api/profiles/sign-in", sign_in, methods=["POST"]),
    ]
    if lite:
        routes += [Route(path, robot_only, methods=[method]) for path, method in ROBOT_REQUESTS]
    routes.append(Mount("/static", _Fresh(directory=STATIC), name="static"))

    async def bad_request(request: Request, exc: Exception) -> Response:
        return _problems([str(exc)], 400)

    handlers: dict[Any, Callable[[Request, Exception], Awaitable[Response]]] = {
        _NotFoundError: not_found,
        _BadRequestError: bad_request,
    }
    app = Starlette(routes=routes, exception_handlers=handlers, max_body_size=MAX_UPLOAD + 1024)
    app.add_middleware(Guard, token=token)
    return app
