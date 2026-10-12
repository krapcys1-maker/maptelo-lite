"""Build the portable Maptelo for Windows: a folder (zipped by CI) that runs from wherever
it is unpacked, with no installation and no administrator rights (docs/08-srodowiska.md).

    python tools/package/build_portable.py --python-zip python-3.12.10-embed-amd64.zip \
        --wheel dist/maptelo-0.0.1-py3-none-any.whl --out build/Maptelo [--with-chromium] [--lite]

``--lite``: Maptelo Lite, which records a process and makes its map (steps, SOP, BPMN, report)
and has no robot: Studio in its Lite mode on Documents\\Maptelo Lite, no MCP server, no
Chromium (the recording uses the company's Edge), ``Maptelo Lite.cmd`` instead of the others.

    Maptelo/
      python/                  Python's own "embeddable" build, with Maptelo in site-packages
      browsers/                Chromium for the robot (only --with-chromium; else Edge is used)
      Maptelo Studio.cmd       opens Studio in its own window, on Documents\\Maptelo
      maptelo.cmd              the command line
      policy.example.yaml      what IT may decide (docs/08-srodowiska.md)
      CZYTAJ.txt               how to start, in Polish

Runs on Windows (CI's windows runner); the embeddable zip is downloaded and checked there,
never on a person's computer.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

STUDIO_CMD = r"""@echo off
rem Maptelo Studio: its own window (Edge in app mode); closing it stops Studio.
setlocal
set "HERE=%~dp0"
if exist "%HERE%browsers" set "PLAYWRIGHT_BROWSERS_PATH=%HERE%browsers"
set "WORK=%USERPROFILE%\Documents\Maptelo"
rem Processes made before the rename (Stepproof) are used where they are.
set "BEFORE=%USERPROFILE%\Documents\Stepproof"
if not exist "%WORK%" if exist "%BEFORE%" set "WORK=%BEFORE%"
if not exist "%WORK%" mkdir "%WORK%"
start "Maptelo Studio" /min "%HERE%python\python.exe" -m maptelo studio --workspace "%WORK%" %*
"""

CLI_CMD = r"""@echo off
rem The Maptelo command line: maptelo --help
setlocal
set "HERE=%~dp0"
if exist "%HERE%browsers" set "PLAYWRIGHT_BROWSERS_PATH=%HERE%browsers"
"%HERE%python\python.exe" -m maptelo %*
"""

LITE_CMD = r"""@echo off
rem Maptelo Lite: record a process, get its map (steps, SOP, BPMN, report). No robot.
setlocal
set "HERE=%~dp0"
set "WORK=%USERPROFILE%\Documents\Maptelo Lite"
if not exist "%WORK%" mkdir "%WORK%"
start "Maptelo Lite" /min "%HERE%python\python.exe" -m maptelo.lite studio --workspace "%WORK%" %*
"""

LITE_README = """\
Maptelo Lite
============

Nagrywa proces zrobiony w przeglądarce i robi z niego mapę: kroki, instrukcję krok po kroku
(SOP), diagram BPMN i raport HTML. Nie uruchamia procesów (to robi pełne Maptelo).
Nie wymaga uprawnień administratora.

  Maptelo Lite.cmd       okno Maptelo Lite (Edge w trybie aplikacji); folder roboczy:
                         Dokumenty\\Maptelo Lite. Zamknięcie okna zamyka program.

Jak zacząć: „Nowy proces: nagraj”, wpisz nazwę i adres startowy, zrób proces w oknie, które
się otworzy, i zamknij je. Mapa pojawi się sama. W „Gotowości” możesz raz zalogować się do
aplikacji, żeby nagrywanie pamiętało logowanie.

To prototyp: plik nie jest podpisany, więc Windows może zapytać, czy go uruchomić.
"""

POLICY_EXAMPLE = """\
# What IT may decide for Maptelo on this computer (docs/08-srodowiska.md).
# To make it apply: copy it to %ProgramData%\\Maptelo\\policy.yaml (the whole computer)
# or next to this file as policy.yaml (this copy only). A file that cannot be read stops
# Maptelo from doing anything until it is fixed.
ai:
  allowed: false                    # no calls to AI models at all
  # endpoint: https://ai.firma.pl/v1  # or: only through the company's gateway
applications:
  allowed_hosts: [erp.firma.local, "*.firma.pl", login.microsoftonline.com]
browser:
  channel: msedge                   # the company's browser
"""

README = """\
Maptelo, wersja przenośna
=========================

Nie wymaga instalacji ani uprawnień administratora. Rozpakuj folder w dowolne miejsce,
w którym wolno uruchamiać programy (np. Dokumenty), i uruchom:

  Maptelo Studio.cmd     Studio we własnym oknie (Edge w trybie aplikacji); folder roboczy:
                         Dokumenty\\Maptelo. Zamknięcie okna zamyka Studio.
  maptelo.cmd            wiersz poleceń, np.: maptelo.cmd doctor

Na początek: w Studio otwórz „Gotowość” i sprawdź „Ten komputer”: Maptelo mówi tam, co na
tym komputerze działa, czego użyje zamiast tego, czego nie ma, i o co ewentualnie poprosić IT.

Zasady od IT: zobacz policy.example.yaml.
"""


def _patch_paths(python: Path) -> None:
    """The embeddable build ignores site-packages until its ._pth file says otherwise."""
    (pth,) = python.glob("python3*._pth")
    lines = pth.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.strip() not in ("#import site", "import site")]
    # Explicit package paths suffice for the wheels. Importing site also loads the user's
    # roaming site-packages, making a portable build depend on arbitrary machine packages.
    pth.write_text("\n".join([*kept, "Lib\\site-packages", ""]), encoding="utf-8")


def _install(python: Path, wheel: Path, *, lite: bool = False) -> None:
    target = python / "Lib" / "site-packages"
    target.mkdir(parents=True, exist_ok=True)
    uv = shutil.which("uv")
    extras = "studio" if lite else "studio,mcp"  # Lite has no agents, so no MCP server
    name = wheel.name.split("-")[0].replace("_", "-")  # maptelo, or maptelo-lite (its own repo)
    spec = f"{name}[{extras}] @ {wheel.resolve().as_uri()}"
    if uv is not None:
        command = [uv, "pip", "install", "--target", str(target), "--python", sys.executable, spec]
    else:
        command = [sys.executable, "-m", "pip", "install", "--target", str(target), spec]
    subprocess.run(command, check=True)


def _chromium(out: Path) -> None:
    environment = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(out / "browsers")}
    subprocess.run(
        [str(out / "python" / "python.exe"), "-m", "playwright", "install", "chromium"],
        check=True,
        env=environment,
    )


def build(
    python_zip: Path, wheel: Path, out: Path, *, with_chromium: bool = False, lite: bool = False
) -> Path:
    if out.exists():
        shutil.rmtree(out)
    python = out / "python"
    python.mkdir(parents=True)
    with zipfile.ZipFile(python_zip) as archive:
        archive.extractall(python)
    _patch_paths(python)
    _install(python, wheel, lite=lite)
    if with_chromium and not lite:
        _chromium(out)
    files = (
        [("Maptelo Lite.cmd", LITE_CMD), ("policy.example.yaml", POLICY_EXAMPLE),
         ("CZYTAJ.txt", LITE_README)]
        if lite
        else [("Maptelo Studio.cmd", STUDIO_CMD), ("maptelo.cmd", CLI_CMD),
              ("policy.example.yaml", POLICY_EXAMPLE), ("CZYTAJ.txt", README)]
    )  # fmt: skip
    for name, text in files:
        newline = "\r\n" if name.endswith((".cmd", ".txt")) else "\n"
        (out / name).write_text(text, encoding="utf-8", newline=newline)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python-zip", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--with-chromium", action="store_true")
    parser.add_argument("--lite", action="store_true", help="Maptelo Lite: maps only, no robot")
    args = parser.parse_args()
    built = build(
        args.python_zip, args.wheel, args.out, with_chromium=args.with_chromium, lite=args.lite
    )
    print(f"built {built}")


if __name__ == "__main__":
    main()
