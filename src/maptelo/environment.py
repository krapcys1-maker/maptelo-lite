"""What this computer allows: looked at, not assumed, and nothing sent anywhere.

Maptelo meets open laptops, company computers behind a proxy, and computers where little
is allowed. The probe looks at what is there and says what Maptelo will use and what it
will do without (docs/08-srodowiska.md):
- browsers;
- the policies that block driving them;
- whether Studio can have a window of its own;
- the proxy and the trust store;
- rights;
- the loopback port;
- the workspace;
- IT's policy file.

Nothing here touches the network, so it takes a fraction of a second and can run whenever
Studio starts. What the computer answers comes through ``Machine``, so every situation can be
tested on any computer.
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import socket
import sys
import tempfile
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from maptelo import net
from maptelo.checks import Check, Lang, say
from maptelo.policy import Policy, PolicyError, load_policy, policy_path

if TYPE_CHECKING:
    from maptelo.desktop.jab import BridgeLibrary

EDGE_POLICIES = r"SOFTWARE\Policies\Microsoft\Edge"
CHROME_POLICIES = r"SOFTWARE\Policies\Google\Chrome"
EDGE_UPDATE = r"Microsoft\EdgeUpdate\Clients\{56EB18F8-B008-4CBD-B6D2-8C97FE7E9062}"
APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
VERSION = re.compile(r"\d+(\.\d+){3}")
LOW_SPACE = 2 * 1024**3
"""Below this, a few hundred runs' screenshots may fill the disk."""


class Registry(Protocol):
    def value(self, hive: str, path: str, name: str) -> object | None:
        """A value under HKLM or HKCU, or None when the key or the value is not there."""


class WindowsRegistry:
    def value(self, hive: str, path: str, name: str) -> object | None:
        if sys.platform != "win32":  # the registry is Windows' alone (type checks elsewhere too)
            return None
        import winreg

        root = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}[hive]
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                found: object = winreg.QueryValueEx(key, name)[0]
                return found
        except OSError:
            return None


class NoRegistry:
    def value(self, hive: str, path: str, name: str) -> object | None:
        return None


def _is_admin() -> bool:
    if sys.platform != "win32":
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _loopback() -> str | None:
    """None when Studio can listen on 127.0.0.1, else why not."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            probe.listen(1)
    except OSError as exc:
        return str(exc)
    return None


def _java_bridge() -> BridgeLibrary | None:
    """The Java Access Bridge's library, where Java keeps it (an installed Java or the own
    Java of a program open now, Oracle Forms), and the Python that loads it; None: none."""
    from maptelo.desktop.jab import bridge_library, java_frames, program_folder  # when asked

    own = [program_folder(window.pid) for window in java_frames()]
    return bridge_library([folder for folder in own if folder is not None])


def _writable(folder: Path) -> str | None:
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".maptelo-", delete=True):
            pass
    except OSError as exc:
        return str(exc)
    return None


@dataclass
class Machine:
    """What the probe asks the computer; tests give their own answers."""

    registry: Registry = field(
        default_factory=lambda: WindowsRegistry() if sys.platform == "win32" else NoRegistry()
    )
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    windows: bool = sys.platform == "win32"
    exists: Callable[[Path], bool] = Path.exists
    folders: Callable[[Path], list[str]] = field(
        default=lambda p: [c.name for c in p.iterdir() if c.is_dir()] if p.is_dir() else []
    )
    proxies: Callable[[], dict[str, str]] = urllib.request.getproxies
    system_trust: Callable[[], bool] = lambda: net.SYSTEM_TRUST
    is_admin: Callable[[], bool] = _is_admin
    loopback: Callable[[], str | None] = _loopback
    writable: Callable[[Path], str | None] = _writable
    free_space: Callable[[Path], int] = lambda p: shutil.disk_usage(p).free
    java_bridge: Callable[[], BridgeLibrary | None] = _java_bridge


@dataclass(frozen=True)
class Browser:
    name: str
    channel: str | None
    """What ``--channel`` names it (None: Playwright's own Chromium)."""
    version: str
    driving_blocked: bool = False
    path: Path | None = None
    """Where the browser is (None for Playwright's Chromium: Playwright finds it itself)."""


def _newest(versions: list[str]) -> str:
    found = [v for v in versions if VERSION.fullmatch(v)]
    return max(found, key=lambda v: tuple(int(p) for p in v.split("."))) if found else ""


def _installed(
    machine: Machine, exe: str, update_key: str | None, fallbacks: list[Path]
) -> tuple[Path, str] | None:
    """An installed browser: where it is and its version (empty when unknown); None when it
    is not there."""
    paths = [machine.registry.value(hive, rf"{APP_PATHS}\{exe}", "") for hive in ("HKLM", "HKCU")]
    candidates = [Path(str(p)) for p in paths if p] + fallbacks
    found = next((p for p in candidates if machine.exists(p)), None)
    if found is None:
        return None
    if update_key is not None:
        for path in (rf"SOFTWARE\WOW6432Node\{update_key}", rf"SOFTWARE\{update_key}"):
            known = machine.registry.value("HKLM", path, "pv")
            if isinstance(known, str) and VERSION.fullmatch(known):
                return found, known
    return found, _newest(machine.folders(found.parent))


def _blocked(machine: Machine, policies: str) -> bool:
    """RemoteDebuggingAllowed = 0 turns off --remote-debugging-pipe: Playwright cannot drive."""
    return any(
        machine.registry.value(hive, policies, "RemoteDebuggingAllowed") == 0
        for hive in ("HKLM", "HKCU")
    )


def browsers(machine: Machine) -> list[Browser]:
    """The browsers Maptelo could drive here, the company's first."""
    env = machine.environ
    found = []
    program_files = [env.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles")]
    edge = _installed(
        machine,
        "msedge.exe",
        EDGE_UPDATE,
        [Path(p) / "Microsoft/Edge/Application/msedge.exe" for p in program_files if p],
    )
    if edge is not None:
        found.append(
            Browser("Microsoft Edge", "msedge", edge[1], _blocked(machine, EDGE_POLICIES), edge[0])
        )
    chrome_places = [env.get("ProgramFiles"), env.get("ProgramFiles(x86)"), env.get("LOCALAPPDATA")]
    chrome = _installed(
        machine,
        "chrome.exe",
        None,
        [Path(p) / "Google/Chrome/Application/chrome.exe" for p in chrome_places if p],
    )
    if chrome is not None:
        found.append(
            Browser(
                "Google Chrome", "chrome", chrome[1], _blocked(machine, CHROME_POLICIES), chrome[0]
            )
        )
    browsers_path = env.get("PLAYWRIGHT_BROWSERS_PATH") or (
        str(Path(env["LOCALAPPDATA"]) / "ms-playwright")
        if machine.windows and env.get("LOCALAPPDATA")
        else str(Path.home() / ".cache" / "ms-playwright")
    )
    builds = sorted(
        (f for f in machine.folders(Path(browsers_path)) if re.fullmatch(r"chromium-\d+", f)),
        key=lambda f: int(f.split("-")[1]),
    )
    if builds:
        found.append(Browser("Chromium (Playwright)", None, builds[-1]))
    return found


def _browser_checks(machine: Machine, lang: Lang) -> list[Check]:
    found = browsers(machine)
    if not found:
        return [
            Check(
                "FAIL",
                "browsers",
                say(
                    lang,
                    "no browser Maptelo can control (Edge, Chrome or Chromium from Playwright)",
                    "brak przeglądarki, którą Maptelo może sterować (Edge, Chrome lub Chromium "
                    "z Playwright)",
                ),
                say(
                    lang,
                    "install Edge or Chrome, or run: playwright install chromium",
                    "zainstaluj Edge lub Chrome albo uruchom: playwright install chromium",
                ),
            )
        ]
    listed = ", ".join(f"{b.name} {b.version}".strip() for b in found)
    checks = [Check("ok", "browsers", listed)]
    usable = [b for b in found if not b.driving_blocked]
    for browser in found:
        if browser.driving_blocked:
            checks.append(
                Check(
                    "info" if usable else "FAIL",
                    "driving",
                    say(
                        lang,
                        f"{browser.name}: the RemoteDebuggingAllowed policy blocks browser control",
                        f"{browser.name}: zasada RemoteDebuggingAllowed blokuje sterowanie "
                        "przeglądarką",
                    ),
                    say(
                        lang,
                        f"Maptelo uses {usable[0].name}",
                        f"Maptelo użyje: {usable[0].name}",
                    )
                    if usable
                    else say(
                        lang,
                        "ask IT to allow RemoteDebuggingAllowed for the company browser, "
                        "or to allow Chromium from Playwright",
                        "poproś dział IT o ustawienie RemoteDebuggingAllowed dla firmowej "
                        "przeglądarki albo o dopuszczenie Chromium z Playwright",
                    ),
                )
            )
    if not any(b.driving_blocked for b in found):
        checks.append(
            Check(
                "ok",
                "driving",
                say(
                    lang,
                    "no policy blocks browser control",
                    "żadne zasady nie blokują sterowania przeglądarką",
                ),
            )
        )
    if any(
        machine.registry.value(hive, EDGE_POLICIES, "DeveloperToolsAvailability") == 2
        for hive in ("HKLM", "HKCU")
    ):
        checks.append(
            Check(
                "info",
                "developer tools",
                say(
                    lang,
                    "the policy DeveloperToolsAvailability turns developer tools off in Edge",
                    "zasada DeveloperToolsAvailability wyłącza narzędzia deweloperskie w Edge",
                ),
                say(
                    lang,
                    "recording works; importing from Chrome DevTools Recorder is unavailable",
                    "nagrywanie działa; import z Chrome DevTools Recorder jest niedostępny",
                ),
            )
        )
    return checks


def _window_check(machine: Machine, lang: Lang) -> Check:
    """Studio's own window is a company browser in app mode (no remote debugging, so the
    policies that stop driving a browser do not stop it)."""
    shown = [b for b in browsers(machine) if b.channel in ("msedge", "chrome") and b.path]
    if not shown:
        return Check(
            "info",
            "window",
            say(
                lang,
                "no Edge or Chrome: Studio opens in the default browser",
                "brak przeglądarek Edge i Chrome: Studio otwiera się w przeglądarce domyślnej",
            ),
        )
    return Check(
        "ok",
        "window",
        say(
            lang,
            f"Studio runs in its own window ({shown[0].name} in app mode)",
            f"Studio działa we własnym oknie ({shown[0].name} w trybie aplikacji)",
        ),
    )


def _java_check(machine: Machine, lang: Lang) -> Check:
    """Java programs (Oracle Forms, Swing) are recorded and run through the Java Access Bridge,
    a library that comes with Java on Windows. Without it the browser still works."""
    if not machine.windows:
        return Check(
            "info",
            "java",
            say(
                lang,
                "Java programs can be recorded on Windows",
                "nagrywanie programów Java jest dostępne w systemie Windows",
            ),
        )
    found = machine.java_bridge()
    if found is None:
        return Check(
            "info",
            "java",
            say(
                lang,
                "no Java Access Bridge in this computer's Java or in any open Java program: Java "
                "programs cannot be recorded or run yet (browser applications work)",
                "brak Java Access Bridge w środowisku Java komputera i w otwartych programach "
                "Java: nagrywanie i uruchamianie programów Java nie jest na razie możliwe "
                "(aplikacje przeglądarkowe działają)",
            ),
            say(
                lang,
                "the bridge is part of Java: start the Java program and check again (Maptelo also "
                "looks in the program's own Java)",
                "Java Access Bridge jest częścią środowiska Java: uruchom program Java i sprawdź "
                "ponownie (Maptelo szuka go również w środowisku Java programu)",
            ),
        )
    bits = found.bits
    if not found.usable:  # a library of the other bitness, and no Python of its bitness
        own = 64 if bits == 32 else 32
        return Check(
            "FAIL",
            "java",
            say(
                lang,
                f"this computer's Java is {bits}-bit ({found.path}) and Maptelo's Python "
                f"{own}-bit: Maptelo then reads Java programs through a {bits}-bit Python, and "
                "none was found",
                f"Java na tym komputerze jest {bits}-bitowa ({found.path}), a Python Maptelo "
                f"{own}-bitowy: programy Java są wtedy odczytywane przez {bits}-bitowy Python, "
                "którego nie znaleziono",
            ),
            say(
                lang,
                f"install Maptelo again: its current version brings a {bits}-bit Python along "
                f"(the python{bits} folder); otherwise IT installs Python 3.12 ({bits}-bit) for "
                "this user, which needs no administrator rights",
                f"zainstaluj ponownie Maptelo: aktualna wersja zawiera {bits}-bitowy Python "
                f"(folder python{bits}); w przeciwnym razie dział IT instaluje dla tego "
                f"użytkownika Pythona 3.12 ({bits}-bitowego), co nie wymaga uprawnień "
                "administratora",
            ),
        )
    seen = str(found.path)
    if found.python is not None:
        seen_en = f"{seen}, {bits}-bit, through the {bits}-bit Python {found.python}"
        seen_pl = f"{seen}, {bits}-bitowy, przez {bits}-bitowy Python {found.python}"
    else:
        seen_en = seen_pl = seen
    return Check(
        "ok",
        "java",
        say(
            lang,
            f"Java programs can be recorded and run (Java Access Bridge: {seen_en})",
            f"programy Java mogą być nagrywane i uruchamiane (Java Access Bridge: {seen_pl})",
        ),
        say(
            lang,
            "if a program is missing from the list when recording, its Java Access Bridge is off; "
            "IT can enable it with jabswitch -enable",
            "jeśli programu nie ma na liście przy nagrywaniu, Java Access Bridge jest w nim "
            "wyłączony; dział IT może go włączyć poleceniem jabswitch -enable",
        ),
    )


def _network_checks(machine: Machine, lang: Lang) -> list[Check]:
    checks = []
    proxies = {k: v for k, v in machine.proxies().items() if k in ("http", "https")}
    if proxies:
        through = ", ".join(f"{k}: {v}" for k, v in sorted(proxies.items()))
        checks.append(
            Check(
                "info",
                "proxy",
                say(
                    lang,
                    f"connections go through a proxy ({through})",
                    f"połączenia przechodzą przez proxy ({through})",
                ),
            )
        )
    else:
        checks.append(
            Check(
                "ok",
                "proxy",
                say(lang, "no proxy: direct connections", "bez proxy: połączenia bezpośrednie"),
            )
        )
    script = machine.registry.value("HKCU", INTERNET_SETTINGS, "AutoConfigURL")
    if script:
        checks.append(
            Check(
                "info",
                "proxy script",
                say(
                    lang,
                    f"Windows selects the proxy with a script ({script}), which Maptelo cannot run",
                    f"Windows wybiera proxy za pomocą skryptu ({script}), którego Maptelo "
                    "nie uruchamia",
                ),
                say(
                    lang,
                    "if AI repairs cannot connect, set HTTPS_PROXY to the company proxy",
                    "jeśli naprawy AI nie mogą nawiązać połączenia, ustaw HTTPS_PROXY na adres "
                    "firmowego proxy",
                ),
            )
        )
    if machine.system_trust():
        checks.append(
            Check(
                "ok",
                "certificates",
                say(
                    lang,
                    "HTTPS certificates are verified by the system, as in the browser",
                    "certyfikaty HTTPS weryfikuje system, tak jak w przeglądarce",
                ),
            )
        )
    else:
        checks.append(
            Check(
                "info",
                "certificates",
                say(
                    lang,
                    "HTTPS certificates are verified by Python, not by the system",
                    "certyfikaty HTTPS weryfikuje Python, a nie system",
                ),
                say(
                    lang,
                    "behind a TLS-inspecting proxy, install truststore",
                    "za proxy z inspekcją TLS zainstaluj pakiet truststore",
                ),
            )
        )
    return checks


def _machine_checks(machine: Machine, workspace: Path | None, lang: Lang) -> list[Check]:
    checks = [
        Check(
            "info",
            "rights",
            say(
                lang,
                "administrator (Maptelo does not require these rights)",
                "administrator (Maptelo nie wymaga tych uprawnień)",
            ),
        )
        if machine.is_admin()
        else Check(
            "ok",
            "rights",
            say(
                lang,
                "standard user: sufficient, administrator rights are not required",
                "konto standardowe: wystarcza, uprawnienia administratora nie są wymagane",
            ),
        )
    ]
    problem = machine.loopback()
    if problem is None:
        checks.append(
            Check(
                "ok",
                "loopback",
                say(
                    lang,
                    "Studio can listen on 127.0.0.1",
                    "Studio może działać pod adresem 127.0.0.1",
                ),
            )
        )
    else:
        checks.append(
            Check(
                "FAIL",
                "loopback",
                say(
                    lang,
                    f"cannot listen on 127.0.0.1: {problem}",
                    f"Studio nie może działać pod adresem 127.0.0.1: {problem}",
                ),
                say(
                    lang,
                    "security software may block local ports: ask IT for an exception for Maptelo",
                    "oprogramowanie zabezpieczające może blokować porty lokalne: poproś dział IT "
                    "o wyjątek dla Maptelo",
                ),
            )
        )
    if workspace is not None:
        checks.append(_workspace_check(machine, workspace, lang))
    checks.append(_policy_check(machine, lang))
    return checks


def _policy_check(machine: Machine, lang: Lang) -> Check:
    try:
        found = it_policy(machine)
    except PolicyError as exc:
        return Check(
            "FAIL",
            "policy",
            str(exc),
            say(
                lang,
                "ask IT to correct the policy: until then Maptelo will not run processes or use AI",
                "poproś dział IT o poprawienie zasad: do tego czasu Maptelo nie uruchomi procesów "
                "ani nie skorzysta z AI",
            ),
        )
    if found.source is None:
        return Check(
            "ok",
            "policy",
            say(
                lang,
                "no IT policy: default settings apply",
                "brak zasad działu IT: obowiązują ustawienia domyślne",
            ),
        )
    return Check(
        "info",
        "policy",
        say(
            lang,
            f"IT's policy applies ({found.source}): {found.describe(lang)}",
            f"obowiązują zasady działu IT ({found.source}): {found.describe(lang)}",
        ),
    )


def _workspace_check(machine: Machine, workspace: Path, lang: Lang) -> Check:
    problem = machine.writable(workspace)
    if problem is not None:
        return Check(
            "FAIL",
            "workspace",
            say(
                lang,
                f"cannot write to {workspace}: {problem}",
                f"brak możliwości zapisu w {workspace}: {problem}",
            ),
            say(
                lang,
                "choose a folder of your own (e.g. Documents\\Maptelo)",
                "wybierz własny folder (np. Dokumenty\\Maptelo)",
            ),
        )
    notes = []
    free = machine.free_space(workspace)
    gigabytes = free / 1024**3
    if free < LOW_SPACE:
        notes.append(
            say(
                lang,
                f"only {gigabytes:.1f} GB free (screenshots of runs require space)",
                f"tylko {gigabytes:.1f} GB wolnego miejsca (zrzuty ekranu z przebiegów "
                "wymagają miejsca)",
            )
        )
    synced = [machine.environ.get(k) for k in ("OneDrive", "OneDriveCommercial")]
    if any(s and _inside(workspace, s) for s in synced):
        notes.append(
            say(
                lang,
                "synchronised by OneDrive: runs and screenshots are also uploaded to the cloud",
                "folder synchronizowany przez OneDrive: przebiegi i zrzuty ekranu są przesyłane "
                "również do chmury",
            )
        )
    if len(str(workspace)) > 120:
        notes.append(
            say(
                lang,
                "long path: file paths may exceed the 260-character Windows limit",
                "długa ścieżka: ścieżki plików mogą przekroczyć limit 260 znaków systemu Windows",
            )
        )
    if notes:
        return Check("info", "workspace", f"{workspace}: " + "; ".join(notes))
    return Check(
        "ok",
        "workspace",
        say(
            lang,
            f"{workspace}: writable, {gigabytes:.0f} GB free",
            f"{workspace}: zapis możliwy, {gigabytes:.0f} GB wolnego miejsca",
        ),
    )


def _inside(path: Path, folder: str) -> bool:
    """Whether a path is the folder or under it, however either is written."""
    inner = os.path.normcase(os.path.normpath(str(path)))
    outer = os.path.normcase(os.path.normpath(folder)).rstrip("\\/")
    return inner == outer or inner.startswith(outer + os.sep)


def it_policy(machine: Machine) -> Policy:
    """IT's policy for this computer (docs/08-srodowiska.md); PolicyError when unreadable."""
    path = policy_path(machine.environ, exists=machine.exists)
    return load_policy(path) if path is not None else Policy()


def required_browser(machine: Machine | None = None) -> str | None:
    """The browser IT's policy names (Studio's names), or None when the person chooses."""
    try:
        return it_policy(machine or Machine()).rules.browser.channel
    except PolicyError:
        return None


def recommended_browser(machine: Machine | None = None) -> str | None:
    """The browser to offer first: the one IT's policy names; else Playwright's Chromium
    (kept apart from the person's own browser), else the company's Edge, else Chrome; only
    ones no policy forbids driving. Studio's names: chromium, msedge, chrome (None: nothing
    can be driven here)."""
    machine = machine or Machine()
    required = required_browser(machine)
    if required is not None:
        return required
    usable = [b for b in browsers(machine) if not b.driving_blocked]
    for wanted in (None, "msedge", "chrome"):
        if any(b.channel == wanted for b in usable):
            return wanted or "chromium"
    return None


def probe(
    workspace: Path | None = None, machine: Machine | None = None, *, lang: Lang = "en"
) -> list[Check]:
    """Every look at this computer, in the order a person reads them."""
    machine = machine or Machine()
    return [
        *_browser_checks(machine, lang),
        _window_check(machine, lang),
        _java_check(machine, lang),
        *_network_checks(machine, lang),
        *_machine_checks(machine, workspace, lang),
    ]
