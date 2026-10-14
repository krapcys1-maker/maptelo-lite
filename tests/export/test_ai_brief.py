"""The AI brief (ai-brief.md, ai-brief.json): a map as a language model needs it to build the
automation, with what each step did as the recording saw it."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maptelo.export import write_map_bundle
from maptelo.export.ai_brief import ai_brief_data, goal, open_questions, render_ai_brief
from maptelo.export.effects import Effect, effect_text, model_effects, step_effects
from maptelo.mapping import MapResult, map_trace
from maptelo.trace import load_trace
from maptelo.trace.schema import Trace, TraceEvent, TraceHeader, TraceState
from minierp.scenarios import PROCESS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recordings" / PROCESS


@pytest.fixture(scope="module")
def wrong_cpn() -> MapResult:
    return map_trace(load_trace(FIXTURES / "10-wrong-cpn-then-right"))


def _sources(result: MapResult) -> dict[str, tuple[Trace, list[int]]]:
    return {step_id: (result.trace, list(seqs)) for step_id, seqs in result.step_events.items()}


def _step(result: MapResult, name: str) -> str:
    return next(s.id for s in result.model.steps if s.target and s.target[0].name == name)


def test_what_a_save_did_comes_from_the_recording(wrong_cpn: MapResult) -> None:
    effects = model_effects(wrong_cpn.model, _sources(wrong_cpn))
    save = effects[_step(wrong_cpn, "Save")]
    assert Effect("message", "Price saved (version V3).") in save
    assert Effect("rows", "Price versions", "2 → 3") in save
    assert any(e.kind == "page" and "saved=V3" in e.what for e in save)
    words = [effect_text(e, "pl") for e in save]
    assert "komunikat: „Price saved (version V3).”" in words
    assert "tabela „Price versions”: wiersze 2 → 3" in words


def test_the_brief_tells_a_model_everything_it_needs(wrong_cpn: MapResult) -> None:
    effects = model_effects(wrong_cpn.model, _sources(wrong_cpn))
    text = render_ai_brief(
        wrong_cpn.model, lang="pl", notes=wrong_cpn.notes, effects=effects, one_recording=True
    )
    for heading in (
        "## Zadanie",
        "## 1. Karta procesu",
        "## 2. Środowisko i technologia",
        "## 3. Dane wejściowe",
        "## 4. Ekrany",
        "## 5. Kroki",
        "## 6. Decyzje, pętle i reguły",
        "## 7. Wyjątki i okna, które pojawiają się same",
        "## 8. Jak sprawdzić wynik",
        "## 9. Czego nie wiemy",
    ):
        assert heading in text, heading
    assert "Nie klikaj według współrzędnych" in text
    # benchmark M6 r7, the LLM lane: „13 749,68 zł” compared as text with 13749.68 never matched
    assert "liczby jako liczby (ekran pokazuje np. „13 749,68 zł”" in text
    assert '1. role=button name="Save"' in text  # every way of finding the element, in order
    assert "**Co się dzieje po kroku (zaobserwowane w nagraniu):**" in text
    assert "komunikat: „Price saved (version V3).”" in text
    assert "⚑ ten krok zapisuje dane" in text
    assert "| `cpn` |" in text
    assert "jednego nagrania" in text  # one case only: the other cases are asked about
    assert "Mapę utworzono" not in text.split("## 1. Karta procesu")[1].split("\n- **Aplikacja")[0]


def test_the_brief_in_english(wrong_cpn: MapResult) -> None:
    text = render_ai_brief(
        wrong_cpn.model, lang="en", effects=model_effects(wrong_cpn.model, _sources(wrong_cpn))
    )
    assert "## Task" in text
    assert "numbers as numbers" in text
    assert "## 5. Steps" in text
    assert "message: “Price saved (version V3).”" in text
    assert "get_by_role" in text


def test_a_map_bundle_has_the_brief_and_its_data(wrong_cpn: MapResult, tmp_path: Path) -> None:
    files = write_map_bundle(wrong_cpn, tmp_path, lang="pl")
    assert files["ai_brief"].name == "ai-brief.md"
    data = json.loads(files["ai_data"].read_text(encoding="utf-8"))
    assert data["format"] == "maptelo-ai-brief/0.1"
    assert data["process"]["id"] == wrong_cpn.model.id
    save = _step(wrong_cpn, "Save")
    assert {"kind": "message", "what": "Price saved (version V3)."} in data["observed"][save]
    assert data["open_questions"]
    brief = files["ai_brief"].read_text(encoding="utf-8")
    for step_id, picture in data["images"].items():
        assert picture in brief, step_id
        assert (tmp_path / picture).is_file(), step_id


def _java_trace(*, private: bool = False) -> Trace:
    """A Java program's save: its question answered, the window that asked closes, the form
    fills a field by itself and its status line says what was saved."""
    header = TraceHeader(
        recording_id="r1",
        started_at=datetime(2026, 10, 13, tzinfo=UTC),
        start_url="java://wcr/",
        program="WCR",
        private=private,
    )
    before = TraceState(
        id="s1",
        t=1.0,
        url="java://wcr/Cennik",
        aria=(
            '- region "Cennik":\n'
            '  - textbox "Indeks": 26386-F\n'
            '  - combobox "J.m.": ""\n'
            '  - textbox "Cena": "6.04"\n'
            '  - button "Zapisz"\n'
            '- dialog "Indeksy":\n'
            '  - button "OK"'
        ),
    )
    after = TraceState(
        id="s2",
        t=2.0,
        url="java://wcr/Cennik",
        aria=(
            '- region "Cennik":\n'
            '  - textbox "Indeks": 26386-F\n'
            '  - combobox "J.m.": szt.\n'
            '  - textbox "Cena": "6.04"\n'
            '  - button "Zapisz"\n'
            "- status: FRM-40400: Transakcja zakończona: zapisano rekordów: 2."
        ),
    )
    click = TraceEvent(seq=1, t=1.5, type="click", state_before="s1", state_after="s2")
    following = TraceEvent(seq=2, t=3.0, type="click", state_before="s2", state_after="s2")
    return Trace(header=header, events=[click, following], states={"s1": before, "s2": after})


def test_what_a_java_step_did() -> None:
    found = step_effects(_java_trace(), [1], java=True, own={"OK"})
    assert Effect("filled", "J.m.", "szt.") in found
    assert Effect("message", "FRM-40400: Transakcja zakończona: zapisano rekordów: 2.") in found
    assert not any(e.kind == "page" for e in found)  # a Java screen's address is its frame
    # a window the screen after does not show was not closed: a Java screen is one window
    assert not any(e.kind in ("opened", "closed") for e in found)


def test_a_java_step_that_took_the_work_to_another_window() -> None:
    """The list of values closed with its OK: the work goes on in the form under it. Nothing
    of the form is compared with the list's screen (they are two windows)."""
    trace = _java_trace()
    trace.states["s1"] = trace.states["s1"].model_copy(update={"url": "java://wcr/Indeksy"})
    found = step_effects(trace, [1], java=True)
    assert found == [Effect("window", "Cennik")]
    assert effect_text(found[0], "pl") == "dalej praca w oknie „Cennik”"


def test_a_private_recording_gives_no_values() -> None:
    found = step_effects(_java_trace(private=True), [1], java=True)
    assert Effect("filled", "J.m.") in found
    assert Effect("message", "") in found
    assert effect_text(Effect("filled", "J.m."), "pl") == "aplikacja sama wypełnia pole „J.m.”"


def test_the_goal_is_the_persons_not_the_maps_own_sentence(wrong_cpn: MapResult) -> None:
    model = wrong_cpn.model
    told = model.model_copy(
        update={
            "description": "Nowa cena do akceptacji. Mapę utworzono automatycznie na podstawie "
            "nagrania z 13.10.2026."
        }
    )
    assert goal(told) == "Nowa cena do akceptacji."
    bare = model.model_copy(
        update={"description": "Mapę utworzono automatycznie na podstawie nagrania z 13.10.2026."}
    )
    assert goal(bare) == ""
    assert any("cel procesu" in q for q in open_questions(bare, "pl"))
    data = ai_brief_data(bare, lang="pl")
    assert any("cel procesu" in q for q in data["open_questions"])


def test_a_step_done_in_each_row_is_a_loop_in_the_brief() -> None:
    """Importuj unticked in each row with an error (benchmark M3): the brief says the loop,
    and that the table is read again before each row."""
    from maptelo.model.schema import ProcessModel

    model = ProcessModel.model_validate(
        {
            "schema_version": "0.1",
            "id": "m3",
            "version": 1,
            "title": "Import cennika",
            "application": {
                "name": "WCR",
                "kind": "java",
                "window": "WCR",
                "base_url": "java://wcr",
            },
            "steps": [
                {
                    "id": "uncheck_importuj",
                    "intent": "Odznacz „Importuj” w każdym wierszu z błędem",
                    "action": "uncheck",
                    "target": [{"role": "cell", "column": "Importuj"}],
                    "within": {
                        "table": [{"role": "table", "name": "Wiersze pliku"}],
                        "where_not": {"Błąd": None},
                        "pick": "each",
                    },
                }
            ],
        }
    )
    text = render_ai_brief(model, lang="pl")
    assert (
        "W każdym wierszu tabeli „Wiersze pliku”, w którym „Błąd” nie jest puste, po kolei" in text
    )
    assert "pętla po wierszach tabeli „Wiersze pliku”, w których „Błąd” nie jest puste" in text
    english = render_ai_brief(model, lang="en")
    assert "In each row of the table “Wiersze pliku” where “Błąd” is not empty" in english


def test_the_brief_says_how_to_check_the_result_in_full() -> None:
    """The screen, the record's rows by their values, what they show, and that the record
    writes several rows (benchmark M3's import): a model building the check from the brief
    had only the menu's path."""
    from maptelo.model.schema import ProcessModel

    model = ProcessModel.model_validate(
        {
            "schema_version": "0.1",
            "id": "m3",
            "version": 1,
            "title": "Import cennika",
            "application": {
                "name": "WCR",
                "kind": "java",
                "window": "WCR",
                "base_url": "java://wcr",
            },
            "inputs": {"plik": {"type": "string", "column": "Plik"}},
            "effects": [
                {
                    "id": "linie",
                    "description": "Linie z pliku czekają na akceptację",
                    "verifier": {
                        "kind": "screen",
                        "menu": ["Widok", "Podgląd linii cennika"],
                        "row": {"Źródło": "import {inputs.plik}"},
                        "expect": {"Status": "do akceptacji"},
                        "rows": "all",
                    },
                }
            ],
            "steps": [
                {
                    "id": "importuj",
                    "intent": "Kliknij „Importuj zaznaczone”",
                    "action": "click",
                    "target": [{"role": "button", "name": "Importuj zaznaczone"}],
                    "risk": "commit",
                }
            ],
        }
    )
    text = render_ai_brief(model, lang="pl")
    section = text.split("## 8.")[1].split("## 9.")[0]
    assert "ekran programu: menu „Widok” > „Podgląd linii cennika”" in section
    assert "wiersz rekordu: „Źródło” =" in section
    assert "ma pokazywać: „Status” = „do akceptacji”" in section
    assert "rekord zapisuje kilka wierszy" in section


def test_what_the_person_said_leads_the_brief_and_the_sop() -> None:
    """The process in the person's words first; at each step why, when, and that a person
    decides; the steps nobody described are what the brief asks about."""
    from maptelo.export.sop import render_sop
    from maptelo.model.schema import ProcessModel

    story = "Co tydzień importuję pliki od negocjatorów; plik z samymi błędami odsyłam."
    button = "button"
    model = ProcessModel.model_validate(
        {
            "schema_version": "0.1",
            "id": "m6",
            "version": 1,
            "title": "Akceptacja faktur",
            "application": {"name": "Portal", "base_url": "http://portal.test"},
            "card": {"story": story, "goal": "Faktury zgodne z WZ są zaakceptowane."},
            "steps": [
                {"id": "open", "intent": "Otwórz portal", "action": "navigate", "value": "/"},
                {
                    "id": "szukaj",
                    "intent": "Kliknij „Szukaj”",
                    "action": "click",
                    "target": [{"role": button, "name": "Szukaj"}],
                    "note": "faktura musi być na liście",
                },
                {
                    "id": "akceptuj",
                    "intent": "Kliknij „Akceptuj”",
                    "action": "click",
                    "target": [{"role": button, "name": "Akceptuj"}],
                    "note": "akceptuję zgodną fakturę",
                    "note_when": "tylko gdy kwoty się zgadzają",
                    "person_decides": True,
                    "executor": "human",
                },
                {
                    "id": "zamknij",
                    "intent": "Kliknij „Zamknij”",
                    "action": "click",
                    "target": [{"role": button, "name": "Zamknij"}],
                },
            ],
        }
    )
    text = render_ai_brief(model, lang="pl")
    assert f"- **Opis procesu (słowami osoby, która go wykonuje):** {story}" in text
    assert "- **Kiedy (słowami osoby nagrywającej):** tylko gdy kwoty się zgadzają" in text
    assert "Tu decyduje człowiek (tak powiedziała osoba nagrywająca)" in text
    unknown = text.split("## 9.")[1]
    assert "Po co są kroki bez opisu: 4 (Kliknij „Zamknij”)?" in unknown
    assert "Jak przebiega proces" not in unknown  # told: no longer asked
    sop = render_sop(model, lang="pl")
    assert f"- **Opis procesu:** {story}" in sop
    assert "   - **Kiedy:** tylko gdy kwoty się zgadzają" in sop
    assert "Tu decyduje człowiek" in sop


def test_a_choice_from_a_list_may_be_the_options_value_or_its_text(wrong_cpn: MapResult) -> None:
    """M7's maps of one recording: the scripts chose the chain „K0017” by the options' visible
    text, found none and stopped at every record (the robot matches both)."""
    from maptelo.model.schema import Action

    model = wrong_cpn.model
    chosen = [s for s in model.steps if s.action is Action.SELECT_OPTION and s.value]
    assert chosen
    hint = "Dana może być wartością opcji (value), jej widocznym tekstem albo kodem"
    assert render_ai_brief(model, lang="pl").count(hint) == len(chosen)
    assert "The input may be the option's value, its visible text, or the code" in (
        render_ai_brief(model, lang="en")
    )


def test_the_brief_says_where_the_result_is_read_and_not_to_wait_for_load(
    wrong_cpn: MapResult,
) -> None:
    """A model given M7's brief read /read/cennik from the portal's own address (its HTML page,
    not the API's answer) and broke after the write; M5's scripts waited for a „load” a slow
    resource never let come."""
    from maptelo.model.schema import Effect as ModelEffect
    from maptelo.model.schema import HttpVerifier

    model = wrong_cpn.model
    read = HttpVerifier(url="/read/cennik?siec={inputs.siec}", expect={"zaimportowany": True})
    application = model.application.model_copy(update={"api_base_url": "http://portal.test/api"})
    model = model.model_copy(
        update={
            "application": application,
            "effects": [
                ModelEffect(id="cennik", description="Cennik zaimportowany", verifier=read)
            ],
        }
    )
    brief = render_ai_brief(model, lang="pl")
    assert "`http://portal.test/api/read/cennik?siec={inputs.siec}`" in brief
    assert "**Adres odczytu (API) do sprawdzenia wyniku:** http://portal.test/api" in brief
    assert 'wait_until="domcontentloaded"' in brief
