"""The probe on made-up computers: open, behind a proxy, locked down by policies, with nothing
installed. Each answer comes from a Machine the test builds, so every case runs anywhere."""

from __future__ import annotations

from pathlib import Path

import pytest

from maptelo.desktop.jab import BridgeLibrary, python_bits
from maptelo.environment import (
    CHROME_POLICIES,
    EDGE_POLICIES,
    EDGE_UPDATE,
    Machine,
    browsers,
    probe,
    recommended_browser,
)

PF86 = "C:/Program Files (x86)"
PF = "C:/Program Files"
LOCAL = "C:/Users/ola/AppData/Local"
EDGE_EXE = Path(PF86) / "Microsoft/Edge/Application/msedge.exe"
CHROME_EXE = Path(LOCAL) / "Google/Chrome/Application/chrome.exe"
JAB = Path(PF) / "Eclipse Adoptium/jdk-21/bin/WindowsAccessBridge-64.dll"


class FakeRegistry:
    def __init__(self, values: dict[tuple[str, str, str], object]) -> None:
        self.values = values

    def value(self, hive: str, path: str, name: str) -> object | None:
        return self.values.get((hive, path, name))


def machine(
    values: dict[tuple[str, str, str], object] | None = None,
    files: set[Path] | None = None,
    folders: dict[Path, list[str]] | None = None,
    **answers: object,
) -> Machine:
    files = files or set()
    folders = folders or {}
    made = Machine(
        registry=FakeRegistry(values or {}),
        environ={
            "ProgramFiles(x86)": PF86,
            "ProgramFiles": PF,
            "LOCALAPPDATA": LOCAL,
            "ProgramData": "C:/ProgramData",
            "OneDrive": "C:/Users/ola/OneDrive",
        },
        windows=True,
        exists=lambda p: p in files,
        folders=lambda p: folders.get(p, []),
        proxies=dict,
        system_trust=lambda: True,
        is_admin=lambda: False,
        loopback=lambda: None,
        writable=lambda p: None,
        free_space=lambda p: 500 * 1024**3,
        java_bridge=lambda: BridgeLibrary(JAB, python_bits()),
    )
    for name, answer in answers.items():
        setattr(made, name, answer)
    return made


def verdicts(checks: list[object]) -> dict[str, str]:
    return {c.what: c.verdict for c in checks}  # type: ignore[attr-defined]


def test_an_open_computer() -> None:
    computer = machine(
        values={
            ("HKLM", rf"SOFTWARE\WOW6432Node\{EDGE_UPDATE}", "pv"): "141.0.3537.71",
        },
        files={EDGE_EXE, CHROME_EXE},
        folders={
            CHROME_EXE.parent: ["140.0.7339.80", "141.0.7390.54", "SetupMetrics"],
            Path(LOCAL) / "ms-playwright": ["chromium-1187", "chromium-1234", "ffmpeg-1011"],
        },
    )
    found = browsers(computer)
    assert [(b.name, b.channel, b.version) for b in found] == [
        ("Microsoft Edge", "msedge", "141.0.3537.71"),
        ("Google Chrome", "chrome", "141.0.7390.54"),  # the newest version folder
        ("Chromium (Playwright)", None, "chromium-1234"),
    ]
    checks = probe(Path("D:/Robot"), computer)
    assert set(verdicts(checks).values()) == {"ok"}


def test_a_policy_that_forbids_driving_edge_falls_back_to_chromium() -> None:
    computer = machine(
        values={("HKLM", EDGE_POLICIES, "RemoteDebuggingAllowed"): 0},
        files={EDGE_EXE},
        folders={Path(LOCAL) / "ms-playwright": ["chromium-1234"]},
    )
    (edge, chromium) = browsers(computer)
    assert (edge.driving_blocked, chromium.driving_blocked) == (True, False)
    driving = next(c for c in probe(None, computer) if c.what == "driving")
    assert driving.verdict == "info"
    assert "RemoteDebuggingAllowed" in driving.detail
    assert driving.hint == "Maptelo uses Chromium (Playwright)"


def test_when_every_browser_is_forbidden_it_says_what_to_ask_it_for() -> None:
    computer = machine(
        values={
            ("HKCU", EDGE_POLICIES, "RemoteDebuggingAllowed"): 0,
            ("HKLM", CHROME_POLICIES, "RemoteDebuggingAllowed"): 0,
            ("HKLM", EDGE_POLICIES, "DeveloperToolsAvailability"): 2,
        },
        files={EDGE_EXE, CHROME_EXE},
    )
    checks = probe(None, computer)
    driving = [c for c in checks if c.what == "driving"]
    assert [c.verdict for c in driving] == ["FAIL", "FAIL"]
    assert "ask IT to allow RemoteDebuggingAllowed" in driving[0].hint
    assert verdicts(checks)["developer tools"] == "info"


def test_a_computer_with_nothing_to_drive() -> None:
    checks = probe(None, machine())
    browsers_check = next(c for c in checks if c.what == "browsers")
    assert browsers_check.verdict == "FAIL"
    assert "playwright install chromium" in browsers_check.hint
    assert verdicts(checks)["window"] == "info"  # no Edge or Chrome: the default browser


def test_behind_a_proxy_with_a_script_and_without_windows_trust() -> None:
    computer = machine(
        values={
            (
                "HKCU",
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                "AutoConfigURL",
            ): "http://wpad.firma.local/proxy.pac",
        },
        proxies=lambda: {"https": "http://proxy.firma.local:8080", "no": "localhost"},
        system_trust=lambda: False,
    )
    checks = {c.what: c for c in probe(None, computer)}
    assert checks["proxy"].detail == (
        "connections go through a proxy (https: http://proxy.firma.local:8080)"
    )
    assert "proxy script" not in checks  # Lite connects nowhere itself
    assert checks["certificates"].verdict == "info"


@pytest.mark.parametrize(
    ("answers", "verdict", "words"),
    [
        ({"writable": lambda p: "Access is denied"}, "FAIL", "cannot write"),
        ({"free_space": lambda p: 1024**3}, "info", "only 1.0 GB free"),
        ({}, "info", "synchronised by OneDrive"),
    ],
)
def test_the_workspace(answers: dict[str, object], verdict: str, words: str) -> None:
    folder = Path("C:/Users/ola/OneDrive/Robot") if not answers else Path("D:/Robot")
    check = next(c for c in probe(folder, machine(**answers)) if c.what == "workspace")
    assert check.verdict == verdict
    assert words in check.detail


def test_rights_loopback_and_it_policy(tmp_path: Path) -> None:
    rules = tmp_path / "policy.yaml"
    rules.write_text("ai: {allowed: false}\nbrowser: {channel: msedge}\n", encoding="utf-8")
    computer = machine(
        is_admin=lambda: True,
        loopback=lambda: "an attempt was made to access a socket in a way forbidden",
    )
    computer.environ = {**computer.environ, "MAPTELO_POLICY": str(rules)}
    checks = {c.what: c for c in probe(None, computer)}
    assert checks["rights"].verdict == "info"
    assert checks["loopback"].verdict == "FAIL"
    assert checks["policy"].verdict == "info"
    assert checks["policy"].detail == f"IT's policy applies ({rules}): browser: msedge"
    assert recommended_browser(computer) == "msedge"  # whatever else is installed

    rules.write_text("ai: {allowed: maybe}\n", encoding="utf-8")
    broken = next(c for c in probe(None, computer, lang="pl") if c.what == "policy")
    assert broken.verdict == "FAIL"
    assert broken.detail.startswith(f"IT's policy {rules} is not valid: ai.allowed:")
    assert "ustawienia przeglądarki nie są stosowane" in broken.hint


def test_this_computer_answers_quickly_and_without_errors(tmp_path: Path) -> None:
    checks = probe(tmp_path)
    assert {c.what for c in checks} >= {"browsers", "window", "proxy", "rights", "loopback"}


def test_java_programs_need_the_bridge_that_comes_with_java() -> None:
    """Recording a Java program (Oracle Forms, Swing) needs the Java Access Bridge; without it
    the browser still works, so it is no failure, and the page says where it comes from."""
    ready = {c.what: c for c in probe(Path("D:/Robot"), machine())}["java"]
    assert ready.verdict == "ok"
    assert str(JAB) in ready.detail
    assert "jabswitch -enable" in ready.hint
    without = machine(java_bridge=lambda: None)
    missing = {c.what: c for c in probe(Path("D:/Robot"), without, lang="pl")}["java"]
    assert missing.verdict == "info"
    assert missing.detail.startswith("brak Java Access Bridge")
    elsewhere = machine(windows=False)
    assert {c.what: c for c in probe(Path("D:/Robot"), elsewhere)}["java"].verdict == "info"


def test_a_32_bit_java_is_read_through_a_32_bit_python(monkeypatch: pytest.MonkeyPatch) -> None:
    """A computer with only a 32-bit Java (7 or 8) next to Maptelo's 64-bit Python: the bridge
    works through a 32-bit Python (Maptelo Lite brings one); without one, the page says what
    to do instead of saying the bridge is missing."""
    monkeypatch.setattr("maptelo.desktop.jab.python_bits", lambda: 64)
    library = Path(PF86) / "Java/jre8/bin/WindowsAccessBridge-32.dll"
    helper = Path("C:/Users/ola/Desktop/Maptelo Lite/python32/python.exe")
    through = machine(java_bridge=lambda: BridgeLibrary(library, 32, helper))
    ready = {c.what: c for c in probe(Path("D:/Robot"), through)}["java"]
    assert ready.verdict == "ok"
    assert f"{library}, 32-bit, through the 32-bit Python {helper}" in ready.detail
    lacking = machine(java_bridge=lambda: BridgeLibrary(library, 32, None))
    stuck = {c.what: c for c in probe(Path("D:/Robot"), lacking, lang="pl")}["java"]
    assert stuck.verdict == "FAIL"
    assert stuck.detail.startswith("Java na tym komputerze jest 32-bitowa")
    assert "folder python32" in stuck.hint
