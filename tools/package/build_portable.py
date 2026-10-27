"""Build the portable Maptelo for Windows: a folder (zipped by CI) that runs from wherever
it is unpacked, with no installation and no administrator rights (docs/08-srodowiska.md).

    python tools/package/build_portable.py --python-zip python-3.12.10-embed-amd64.zip \
        --python32-zip python-3.12.10-embed-win32.zip \
        --wheel dist/maptelo-0.0.1-py3-none-any.whl --out build/Maptelo [--with-chromium] [--lite]

``--lite``: Maptelo Lite, which records a process and makes its map (steps, SOP, BPMN, report)
and has no robot: Studio in its Lite mode on Documents\\Maptelo Lite, no MCP server, no
Chromium (the recording uses the company's Edge), ``Maptelo Lite.cmd`` instead of the others.

    Maptelo/
      python/                  Python's own "embeddable" build, with Maptelo in site-packages
      python32/                its 32-bit build as it comes: a 32-bit Java's bridge library is
                               loaded there (desktop/jab_remote.py), no administrator rights
      browsers/               Chromium for the robot (only --with-chromium; else Edge is used)
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
rem Everything stays in this folder: the processes in Procesy (Processes), the sign-ins and
rem settings in data. What Lite says goes to data\maptelo-lite.log; this console only says
rem that Lite is starting (its first start may take a minute) and why it could not start.
setlocal
chcp 65001 >nul
set "HERE=%~dp0"
if not exist "%HERE%python\pythonw.exe" goto unpack
set "WORK=%HERE%Procesy"
if exist "%HERE%Processes\" set "WORK=%HERE%Processes"
if not exist "%HERE%Procesy\" if not exist "%HERE%Processes\" (
  reg query "HKCU\Control Panel\International" /v LocaleName 2>nul ^
    | find /i "pl-" >nul || set "WORK=%HERE%Processes"
)
echo Maptelo Lite się uruchamia. Pierwsze uruchomienie może potrwać około minuty.
echo Maptelo Lite is starting. The first start may take about a minute.
"%HERE%python\python.exe" -c "import maptelo.lite" || goto broken
if not exist "%HERE%data\" mkdir "%HERE%data"
set "MAPTELO_LITE_STARTED=%HERE%data\started.txt"
del "%MAPTELO_LITE_STARTED%" 2>nul
start "" "%HERE%python\pythonw.exe" -m maptelo.lite studio ^
  --workspace "%WORK%" --data "%HERE%data" %*
set /a waited=0
:wait
if exist "%MAPTELO_LITE_STARTED%" goto started
>nul ping -n 2 127.0.0.1
set /a waited+=1
if %waited%==60 (
  echo Nadal się uruchamia. Jeśli okno się nie pojawi, zajrzyj do pliku data\maptelo-lite.log.
  echo Still starting. If no window appears, see data\maptelo-lite.log.
)
goto wait
:started
findstr /b "ready" "%MAPTELO_LITE_STARTED%" >nul && exit /b 0
echo.
echo Maptelo Lite nie uruchomiło się. Maptelo Lite did not start:
type "%MAPTELO_LITE_STARTED%"
echo.
echo Szczegóły / details: data\maptelo-lite.log
pause
exit /b 1
:broken
echo.
echo Python z tego folderu nie uruchomił się (przyczyna powyżej). Często blokuje go antywirus
echo albo zasady IT, które nie pozwalają uruchamiać programów z tego miejsca. Przenieś folder
echo MapteloLite, np. do Dokumentów, albo poproś dział IT o zgodę.
echo The Python in this folder did not start (the reason is above). An antivirus or IT rules
echo may block programs in this place: move the MapteloLite folder, e.g. to Documents, or ask IT.
pause
exit /b 1
:unpack
echo Brakuje folderu „python” obok tego pliku: archiwum ZIP nie zostało rozpakowane w całości.
echo Kliknij plik ZIP prawym przyciskiem, wybierz „Wyodrębnij wszystkie…” i uruchom
echo „Maptelo Lite” z rozpakowanego folderu.
echo The "python" folder is missing next to this file: extract the whole ZIP ("Extract all...")
echo and start "Maptelo Lite" from the extracted folder.
pause
exit /b 1
"""

LITE_README = """\
Maptelo Lite
============

Maptelo Lite nagrywa proces wykonywany w przeglądarce lub w programie Java i przygotowuje jego
dokumentację: opis kroków, instrukcję stanowiskową (SOP) ze zrzutami ekranu, diagram BPMN oraz
raport HTML. Program nie wykonuje procesów; służy do tego pełne Maptelo (https://maptelo.dev).
Nie wymaga uprawnień administratora.

Przed uruchomieniem rozpakuj całe archiwum („Wyodrębnij wszystkie…”). Pierwsze uruchomienie
może potrwać około minuty; okno konsoli informuje, że program się uruchamia, i zamyka się,
gdy pojawi się okno Maptelo Lite.

Wszystkie dane pozostają w tym folderze; program nie zapisuje niczego w folderach systemowych
ani w rejestrze Windows:
  Maptelo Lite       uruchamia program (okno Edge w trybie aplikacji; zamknięcie okna kończy pracę)
  Procesy            nagrania i mapy procesów
  data               zapamiętane logowania i ustawienia (nie należy ich udostępniać)
  python             środowisko Python z bibliotekami Maptelo Lite
  python32           32-bitowe środowisko Python dla programów działających w 32-bitowej
                     Javie (na przykład w 32-bitowej Javie 7 lub 8)

Pierwsze kroki: kliknij „Nowy proces”, wprowadź nazwę i adres startowy (albo wybierz program
Java), wykonaj proces w zwykły sposób i zakończ nagrywanie. Mapa zostanie utworzona
automatycznie. W zakładce „Gotowość” można jednorazowo zalogować się do aplikacji, aby
nagrywanie korzystało z zapamiętanego logowania. Język interfejsu (PL/EN) zmienia przełącznik
w lewym dolnym rogu okna.

Wersje 0.x nie mają jeszcze podpisu kodu, dlatego Windows może poprosić o potwierdzenie
uruchomienia.


Maptelo Lite (English)
======================

Maptelo Lite records a process performed in a browser or a Java program and prepares its
documentation: a description of the steps, a work instruction (SOP) with screenshots, a BPMN
diagram and an HTML report. It does not execute processes; that is the full Maptelo
(https://maptelo.dev). No administrator rights are required.

Extract the whole archive ("Extract all...") before starting it. The first start may take
about a minute; a console window says the program is starting and closes when the Maptelo
Lite window appears.

All data stays in this folder; nothing is written to system folders or the Windows registry:
  Maptelo Lite       starts the program (an Edge window in app mode; closing it ends the session)
  Processes          recordings and process maps
  data               saved sign-ins and settings (do not share)
  python             the Python runtime with Maptelo Lite's libraries
  python32           a 32-bit Python runtime for programs running on a 32-bit Java
                     (for example a 32-bit Java 7 or 8)

Getting started: click "New process", enter a name and the start address (or choose a Java
program), perform the process as usual and finish the recording. The map is created
automatically. In the "Readiness" tab you can sign in to the application once, so that
recording uses the saved sign-in. The interface language (PL/EN) is switched in the lower-left
corner of the window.

Versions 0.x are not yet code-signed, so Windows may ask you to confirm running the program.
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


ICON = Path(__file__).resolve().parents[2] / "installer" / "lite" / "maptelo-lite.ico"
"""Maptelo Lite's icon: its shortcuts show it (tools/package/lite_pictures.py draws it)."""


def _patch_paths(python: Path) -> None:
    """The embeddable build ignores site-packages until its ._pth file says otherwise."""
    (pth,) = python.glob("python3*._pth")
    lines = pth.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.strip() not in ("#import site", "import site")]
    # Explicit package paths suffice for the wheels. Importing site also loads the user's
    # roaming site-packages, making a portable build depend on arbitrary machine packages.
    pth.write_text("\n".join([*kept, "Lib\\site-packages", ""]), encoding="utf-8")


def _locked(extras: list[str], out: Path) -> Path | None:
    """The versions uv.lock holds, as a requirements file: the package carries what was
    tested, not whatever an open range gives on the day it is built. None without uv or
    a lock."""
    import importlib.util

    found = shutil.which("uv")
    uv = [found] if found else []
    if not uv and importlib.util.find_spec("uv") is not None:
        uv = [sys.executable, "-m", "uv"]  # uv as a module of this Python (py -m uv)
    lock = Path.cwd() / "uv.lock"
    if not uv or not lock.is_file():
        return None
    wanted = out / "requirements.lock.txt"
    command = [*uv, "export", "--frozen", "--format", "requirements-txt", "--no-emit-project"]
    command += [f"--extra={extra}" for extra in extras] + ["--no-dev", "-o", str(wanted)]
    subprocess.run(command, check=True)
    return wanted


def _install(python: Path, wheel: Path, *, lite: bool = False) -> None:
    target = python / "Lib" / "site-packages"
    target.mkdir(parents=True, exist_ok=True)
    uv = shutil.which("uv")
    extras = ["studio"] if lite else ["studio", "mcp"]  # Lite has no agents, so no MCP server
    name = wheel.name.split("-")[0].replace("_", "-")  # maptelo, or maptelo-lite (its own repo)
    spec = f"{name}[{','.join(extras)}] @ {wheel.resolve().as_uri()}"
    pip = (
        [uv, "pip", "install", "--target", str(target), "--python", sys.executable]
        if uv is not None
        else [sys.executable, "-m", "pip", "install", "--target", str(target)]
    )
    locked = _locked(extras, python.parent)
    if locked is None:
        subprocess.run([*pip, spec], check=True)
        return
    subprocess.run([*pip, "-r", str(locked)], check=True)  # the tested versions first
    subprocess.run([*pip, "--no-deps", str(wheel.resolve())], check=True)


def _compile(python: Path) -> None:
    """Every module compiled now, by the Python that runs them: a first start that compiles
    hundreds of modules while an antivirus reads each file written took a person a minute
    with nothing on the screen (19.10). Checked by hash, never by date: a ZIP keeps no exact
    dates, so a date-checked file would be compiled again anyway. A file that does not compile
    (a library's sample for another Python) is left as it is."""
    subprocess.run(
        [
            str(python / "python.exe"),
            "-m",
            "compileall",
            "-q",
            "--invalidation-mode",
            "unchecked-hash",
            str(python / "Lib" / "site-packages"),
        ],
        check=False,
    )


def _chromium(out: Path) -> None:
    environment = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(out / "browsers")}
    subprocess.run(
        [str(out / "python" / "python.exe"), "-m", "playwright", "install", "chromium"],
        check=True,
        env=environment,
    )


def build(
    python_zip: Path,
    wheel: Path,
    out: Path,
    *,
    with_chromium: bool = False,
    lite: bool = False,
    python32_zip: Path | None = None,
) -> Path:
    if out.exists():
        shutil.rmtree(out)
    python = out / "python"
    python.mkdir(parents=True)
    with zipfile.ZipFile(python_zip) as archive:
        archive.extractall(python)
    _patch_paths(python)
    if python32_zip is not None:  # as it comes: it imports Maptelo from python's site-packages
        with zipfile.ZipFile(python32_zip) as archive:
            archive.extractall(out / "python32")
    _install(python, wheel, lite=lite)
    _compile(python)
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
    if lite:
        shutil.copyfile(ICON, out / ICON.name)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--python-zip", type=Path, required=True)
    parser.add_argument(
        "--python32-zip",
        type=Path,
        help="the 32-bit embeddable Python, in which a 32-bit Java's bridge library is loaded",
    )
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--with-chromium", action="store_true")
    parser.add_argument("--lite", action="store_true", help="Maptelo Lite: maps only, no robot")
    args = parser.parse_args()
    built = build(
        args.python_zip,
        args.wheel,
        args.out,
        with_chromium=args.with_chromium,
        lite=args.lite,
        python32_zip=args.python32_zip,
    )
    print(f"built {built}")


if __name__ == "__main__":
    main()
