"""Maptelo Lite's map page: the SOP is read as a document (its headings, the table of data,
the numbered steps with their notes and screenshots), not as Markdown text (the clean-Windows
Lite test of 12.10 showed it raw); words from the recorded application stay words."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import Browser, expect

from maptelo.studio import Workspace
from maptelo.studio.server import running

pytestmark = pytest.mark.e2e
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recordings"
PROCESS = "update_customer_price"
RECORDING = "01-login-single-version"
TOKEN = "klucz-e2e"

WRITTEN = """# Zmiana ceny <b>klienta</b>

*Proces: `zmiana_ceny` v1 · aplikacja: MiniERP*

> Mapę utworzono automatycznie.

## Dane wejściowe

| Dana | Typ | Opis | Przykład |
|---|---|---|---|
| `cpn` | tekst | Kod \\| CPN | 48212-B |

## Kroki

1. **Otwórz ekran „Customer prices”** — adres `/pricing`
   - Oczekiwany wynik: ekran „Customer prices”

   ![1. Otwórz ekran](images/step-01.jpg)

2. **Kliknij „<img src=x onerror=window.zle=1>”** ⚑ *zapisuje dane*
   - Oczekiwany wynik: pojawia się komunikat

*Wygenerowano przez Maptelo.*
"""


@pytest.fixture(autouse=True)
def own_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Lite keeps the language chosen with the person's profiles: here in a folder of the
    test, never in the ~/.maptelo of the computer the tests run on."""
    home = tmp_path / "home"
    monkeypatch.setattr("maptelo.browser.HOME", home)
    return home


def lite_workspace(tmp_path: Path) -> Workspace:
    root = tmp_path / "praca"
    shutil.copytree(FIXTURES / PROCESS / RECORDING, root / "recordings" / PROCESS / RECORDING)
    return Workspace(root)


def test_the_sop_is_a_document_with_its_screenshots(browser: Browser, tmp_path: Path) -> None:
    root = tmp_path / "praca"
    shutil.copytree(FIXTURES / PROCESS / RECORDING, root / "recordings" / PROCESS / RECORDING)
    with running(Workspace(root), TOKEN, lite=True) as base:
        context = browser.new_context(locale="pl-PL")  # a Polish computer: Lite in Polish
        page = context.new_page()
        page.goto(f"{base}/?t={TOKEN}")
        page.evaluate(f"() => {{ location.hash = '#/p/{PROCESS}'; }}")
        page.get_by_role("button", name="Utwórz mapę").click()
        expect(page.get_by_role("heading", name="Kroki")).to_be_visible()
        sop = page.locator(".sop")
        expect(sop.locator("table")).to_contain_text("valid_from")
        expect(sop.locator("ol > li").first).to_contain_text("Otwórz ekran")
        assert "**" not in sop.inner_text()
        assert "|---" not in sop.inner_text()

        # The SOP as it may be written: a screenshot of a step, a "|" in a cell, and words of
        # the application that look like HTML.
        folder = root / "maps" / PROCESS / RECORDING
        (folder / "sop.md").write_text(WRITTEN, encoding="utf-8")
        (folder / "images").mkdir(exist_ok=True)
        Image.new("RGB", (64, 40), (200, 210, 230)).save(folder / "images" / "step-01.jpg")
        page.evaluate("() => { location.hash = '#/'; }")
        expect(page.get_by_role("heading", name="Procesy")).to_be_visible()
        page.evaluate(f"() => {{ location.hash = '#/p/{PROCESS}/map/{RECORDING}'; }}")
        expect(sop.get_by_role("heading", name="Zmiana ceny <b>klienta</b>")).to_be_visible()
        expect(sop.locator("table td").nth(2)).to_have_text("Kod | CPN")
        second = sop.locator("ol > li").nth(1)
        expect(second).to_contain_text("Kliknij „<img src=x onerror=window.zle=1>”")
        expect(second.locator("strong")).to_have_count(1)
        expect(second.locator("em")).to_have_text("zapisuje dane")
        assert sop.locator("ol > li img").count() == 1  # only the real screenshot
        assert page.evaluate("() => window.zle") is None

        shot = sop.locator("ol > li").first.get_by_role("button", name="Powiększ")
        shot.click()
        box = page.locator("dialog#lightbox")
        expect(box).to_be_visible()
        expect(box.locator(".caption")).to_have_text("1. Otwórz ekran")
        context.close()


def test_lite_speaks_english_once_chosen_and_keeps_it(browser: Browser, tmp_path: Path) -> None:
    workspace = lite_workspace(tmp_path)
    with running(workspace, TOKEN, lite=True) as base:
        context = browser.new_context(locale="pl-PL")
        page = context.new_page()
        page.goto(f"{base}/?t={TOKEN}")
        expect(page.get_by_role("heading", name="Procesy")).to_be_visible()
        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.get_by_role("heading", name="Processes")).to_be_visible()
        expect(page.get_by_role("link", name="Readiness")).to_be_visible()
        expect(page.locator("html")).to_have_attribute("lang", "en")
        page.evaluate(f"() => {{ location.hash = '#/p/{PROCESS}'; }}")
        page.get_by_role("button", name="Create the map", exact=True).click()
        expect(page.get_by_role("heading", name="Work instruction (SOP)")).to_be_visible()
        sop = page.locator(".sop")
        expect(sop.get_by_role("heading", name="Steps", exact=True)).to_be_visible()  # the SOP too
        expect(page.get_by_text("The map is ready:")).to_be_visible()
        page.evaluate("() => { location.hash = '#/new'; }")
        expect(page.get_by_role("button", name="Start recording")).to_be_visible()
        page.evaluate("() => { location.hash = '#/ready'; }")
        expect(page.get_by_role("heading", name="This computer")).to_be_visible()
        context.close()
    # Lite started again opens at another address: the choice is still there
    with running(workspace, TOKEN, lite=True) as base:
        context = browser.new_context(locale="pl-PL")
        page = context.new_page()
        page.goto(f"{base}/?t={TOKEN}")
        expect(page.get_by_role("heading", name="Processes")).to_be_visible()
        page.get_by_role("button", name="PL", exact=True).click()
        expect(page.get_by_role("heading", name="Procesy")).to_be_visible()
        context.close()


def test_lite_starts_in_the_computers_language(browser: Browser, tmp_path: Path) -> None:
    with running(lite_workspace(tmp_path), TOKEN, lite=True) as base:
        for computer, heading in (
            ("en-GB", "Processes"),
            ("de-DE", "Processes"),
            ("pl-PL", "Procesy"),
        ):
            context = browser.new_context(locale=computer)
            page = context.new_page()
            page.goto(f"{base}/?t={TOKEN}")
            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
            context.close()
