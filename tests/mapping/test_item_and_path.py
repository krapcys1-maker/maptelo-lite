"""An item of a list clicked at any of its words is named by the record's value it shows (the
sender of an e-mail, MiniWoB++ email-inbox), and an element named as a part of the record's
value written as a path („Fawn” of „Linzy>Fawn”, click-menu) is the record's, so a person does
it rather than a constant clicking another record's item."""

from __future__ import annotations

from pathlib import Path

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo
from maptelo.trace.schema import DataRef
from tests.mapping.test_many_apps import Recording, found_by_its_words

APP = "http://inbox.test"


def recording(tmp_path: Path, sheet: str, clicked: ElementInfo) -> Recording:
    (tmp_path / "task.csv").write_text(sheet, "utf-8")
    r = Recording()
    page = r.state(f"{APP}/", '- heading "Primary"\n')
    r.add("navigate", f"{APP}/", value=f"{APP}/", state_after=page)
    r.add(
        "click", f"{APP}/", target=found_by_its_words(clicked), state_before=page, state_after=page
    )
    return r


def test_an_e_mail_clicked_at_its_subject_is_named_by_its_sender(tmp_path: Path) -> None:
    subject = ElementInfo(
        tag="div",
        text="Aliquet.",
        pointer=True,
        item=["Rochella", "Aliquet.", "Lorem ipsum dolor sit amet"],
        css="#main > div:nth-of-type(4) > div:nth-of-type(2)",
    )
    r = recording(tmp_path, "by;task\nRochella;delete\n", subject)
    step = map_trace(
        r.trace(tmp_path / "trace.jsonl", DataRef(file="task.csv")), lang="en"
    ).model.steps[-1]
    assert step.target is not None
    assert step.target[0].model_dump(exclude_none=True) == {"text": "{inputs.by}"}
    assert step.executor.value == "deterministic"


def test_an_item_of_a_path_the_record_names_is_done_by_a_person(tmp_path: Path) -> None:
    item = ElementInfo(tag="div", role="menuitem", name="Fawn", css="#ui-id-10")
    r = recording(tmp_path, "target;x\nLinzy>Fawn;y\n", item)
    step = map_trace(
        r.trace(tmp_path / "trace.jsonl", DataRef(file="task.csv")), lang="en"
    ).model.steps[-1]
    assert step.executor.value == "human"


def test_a_document_number_with_slashes_is_no_path(tmp_path: Path) -> None:
    year = ElementInfo(tag="a", role="link", name="2026", css="#years > a")
    r = recording(tmp_path, "zwrot;x\nZW/2026/002;y\n", year)
    step = map_trace(
        r.trace(tmp_path / "trace.jsonl", DataRef(file="task.csv")), lang="en"
    ).model.steps[-1]
    assert step.executor.value == "deterministic"
