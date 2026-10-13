"""Maptelo Lite from the command line: the window, a recording (a browser or a Java program on
this computer) and the map of one recording. The same as the full Maptelo's ``studio --lite``,
``record`` and ``map``; nothing of the robot."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from maptelo import __version__

app = typer.Typer(
    help="Maptelo Lite: do a process once, get its map (steps, SOP, BPMN, report).",
    no_args_is_help=False,
    add_completion=False,
)

WORKSPACE = Path.home() / "Documents" / "Maptelo Lite"
"""Where Lite keeps recordings and maps unless told otherwise (as its installer does)."""


def _fail(message: str) -> NoReturn:
    typer.secho(f"ERROR {message}", fg=typer.colors.RED, bold=True, err=True)
    raise typer.Exit(code=1)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Without a command: the Maptelo Lite window on the usual folder."""
    if ctx.invoked_subcommand is None:
        studio(workspace=WORKSPACE)


@app.command("studio")
def studio(
    workspace: Annotated[
        Path, typer.Option(file_okay=False, help="Folder for recordings and maps.")
    ] = WORKSPACE,
    port: Annotated[int, typer.Option(help="Port on 127.0.0.1 (default: any free one).")] = 0,
    open_page: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the window (or the browser).")
    ] = True,
    window: Annotated[
        bool,
        typer.Option(
            "--window/--no-window",
            help="A window of its own (Edge or Chrome in app mode; closing it stops Lite), or "
            "a tab of the default browser.",
        ),
    ] = True,
    data: Annotated[
        Path | None,
        typer.Option(
            file_okay=False,
            help="Folder for sign-in profiles and the window's browser data (default: "
            "~/.maptelo). The installer keeps it in Lite's own folder.",
        ),
    ] = None,
) -> None:
    """The Maptelo Lite window: record a process and see its map."""
    if data is not None:  # read when the browser's module loads, so before anything imports it
        os.environ["MAPTELO_HOME"] = str(data.resolve())
    try:
        from maptelo.studio import Workspace, serve
    except ImportError as exc:
        _fail(f"the window needs its extra: pip install 'maptelo-lite[studio]' ({exc})")
    workspace.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:  # no console (the shortcut starts pythonw)
        _log_to_file()
    folder = Workspace(workspace)
    typer.echo(f"Maptelo Lite {__version__}, workspace {folder.root}")
    typer.echo("Open this address (it holds a key for this start only); Ctrl+C stops Lite:")
    serve(
        folder,
        port=port,
        open_page=open_page,
        window=window,
        announce=lambda line: typer.echo(f"  {line}"),
        lite=True,
    )


def _log_to_file() -> None:
    """What Lite would say in a console (its address, a problem as it starts) goes to a file
    with its data, where a person or IT can read it."""
    from maptelo.browser import HOME

    HOME.mkdir(parents=True, exist_ok=True)
    log = (HOME / "maptelo-lite.log").open("a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    # what Maptelo's modules tell there too: which Java Access Bridge, through which Python
    told = logging.StreamHandler(log)
    told.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s"))
    logging.getLogger("maptelo").addHandler(told)
    logging.getLogger("maptelo").setLevel(logging.INFO)


@app.command("record")
def record(
    url: Annotated[
        str | None, typer.Argument(help="Where the demonstration starts (a browser).")
    ] = None,
    java: Annotated[
        str | None,
        typer.Option(
            help="Record in a Java desktop program (Swing, AWT) through the Java Access Bridge "
            "instead of a browser: a part of its main window's title."
        ),
    ] = None,
    stop_file: Annotated[
        Path | None,
        typer.Option(help="With --java: stop when this file appears (else Ctrl+C or closing)."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option(help="Recording folder (default: recordings/<process>/<id>).")
    ] = None,
    process: Annotated[
        str | None, typer.Option(help="Process being shown, e.g. zmiana-ceny.")
    ] = None,
    note: Annotated[str | None, typer.Option(help="What is special about this run.")] = None,
    channel: Annotated[
        str | None, typer.Option(help="Use an installed browser: chrome or msedge.")
    ] = None,
    data: Annotated[
        Path | None,
        typer.Option(
            exists=True,
            dir_okay=False,
            help="The workbook (.xlsx) or CSV the values come from (a copy goes with the "
            "recording).",
        ),
    ] = None,
    sheet: Annotated[str | None, typer.Option(help="Sheet of the --data workbook.")] = None,
    private: Annotated[
        bool,
        typer.Option(
            help="Screens show personal data: screenshots cover what is typed and what tables "
            "hold, and maps keep no values."
        ),
    ] = False,
    max_minutes: Annotated[
        float | None, typer.Option(help="Stop automatically after this many minutes.")
    ] = None,
) -> None:
    """Record a demonstration: a browser opens, do the process, close the window to finish.
    With --java: do the process in the Java program, then press Ctrl+C here."""
    from maptelo.capture import RecorderOptions, new_recording_id, record_session
    from maptelo.trace import load_trace, summarize

    folder = out or Path("recordings") / (process or "session") / new_recording_id()
    timeout_s = max_minutes * 60 if max_minutes else None
    if java is not None:
        from maptelo.capture.java import JavaRecorder, JavaRecorderOptions
        from maptelo.desktop.jab import AccessBridgeError

        typer.echo(f"Looking for the Java program '{java}'...")
        options = JavaRecorderOptions(
            window=java,
            process=process,
            note=note,
            data=data,
            sheet=sheet,
            private=private,
            raw_events=bool(os.environ.get("MAPTELO_JAVA_EVENTS")),
        )
        recorder = JavaRecorder(folder, options)
        try:
            main_window = recorder.start()
            typer.echo(
                f"Recording “{main_window.title}” into {folder}: do the process now, then press "
                "Ctrl+C here (or close the program)."
            )
            path = recorder.record_until(stop_file=stop_file, timeout_s=timeout_s)
        except (AccessBridgeError, RuntimeError) as exc:
            _fail(str(exc))
        typer.echo(summarize(load_trace(path)))
        return
    if url is None:
        _fail("say where the demonstration starts (an address), or --java for a Java program")
    typer.echo(f"Recording into {folder}. Do the process in the browser, then close the window.")
    web = RecorderOptions(process=process, note=note, data=data, sheet=sheet, private=private)
    path = record_session(url, folder, web, channel=channel, timeout_s=timeout_s)
    typer.echo(summarize(load_trace(path)))


@app.command("map")
def map_command(
    trace_path: Annotated[Path, typer.Argument(exists=True, help="trace.jsonl or its folder.")],
    out: Annotated[
        Path | None, typer.Option(help="Folder for the map (default: maps/<process>/<recording>).")
    ] = None,
    lang: Annotated[str, typer.Option(help="Language of the documents: pl or en.")] = "pl",
    process_id: Annotated[
        str | None, typer.Option("--id", help="Process id (default: from the recording).")
    ] = None,
) -> None:
    """Map one recording: its steps, the SOP, a diagram, BPMN and an HTML report."""
    from maptelo.export import write_map_bundle
    from maptelo.mapping import map_trace
    from maptelo.mapping.naming import Lang
    from maptelo.trace import TraceError, load_trace

    if lang not in ("pl", "en"):
        _fail("the language is pl or en")
    language: Lang = "en" if lang == "en" else "pl"
    try:
        trace = load_trace(trace_path)
    except TraceError as exc:
        _fail(str(exc))
    result = map_trace(trace, lang=language, process_id=process_id)
    model = result.model
    folder = out or Path("maps") / model.id / trace.header.recording_id
    files = write_map_bundle(result, folder, lang=language)
    typer.secho(f"{model.title}: {len(model.steps)} steps", bold=True)
    typer.echo(f"  inputs: {', '.join(model.inputs) or '-'}")
    for note in result.notes:
        typer.echo(f"  to confirm: {note}")
    for key, path in files.items():
        typer.echo(f"  {key:<8} {path}")


if __name__ == "__main__":
    app()
