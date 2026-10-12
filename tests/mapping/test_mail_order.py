"""An order typed from an e-mail into the ERP (benchmark p11). The sheet names the e-mail by
its subject; the inbox shows the subject inside a cell with the sender and the date (no column
headers). The order's reference stands twice: in the subject (where the inbox lists other
orders' subjects too) and in the text („realizację zamówienia nr PO-10001”). The customer is
picked from the ERP's list by the name the e-mail is signed with."""

from __future__ import annotations

from pathlib import Path

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo
from maptelo.trace.schema import DataRef, RowContext
from tests.mapping.test_many_apps import ERP, Recording, field, found_by_its_words

MAIL = "http://poczta.test/?_task=mail"
SUBJECTS = ("Zamówienie PO-10007", "Zamówienie PO-10006", "Zamówienie PO-10001")
BODY = (
    "Dzień dobry, proszę o realizację zamówienia nr PO-10001: Produkt: 16218-E Ilość: 25 szt. "
    "Pozdrawiam Dział zakupów, Sklep internetowy Grądziel-Lew"
)


def inbox(opened: bool) -> str:
    lines = ['- table "Lista wiadomości e-mail":', "  - rowgroup:"]
    for subject in SUBJECTS:
        lines += [
            f'    - row "Dział zakupów, Firma {subject}":',
            f'      - cell "Dział zakupów, Firma {subject}":',
            "        - text: Dział zakupów, Firma",
            f'        - link "{subject}"',
        ]
    if opened:
        lines += [
            "- main:",
            '  - heading "Zamówienie PO-10001" [level=2]',
            "  - text: Od",
            '  - link "Dział zakupów, Sklep internetowy Grądziel-Lew"',
            f'  - region "Treść wiadomości": "{BODY}"',
        ]
    return "\n".join(lines) + "\n"


ORDER = """- main:
  - heading "Nowe zamówienie" [level=1]
  - combobox "Klient":
    - option "Sklep internetowy Grądziel-Lew (K0013)"
    - option "Sklep internetowy Molak (K0026)"
  - textbox "Numer referencyjny klienta"
  - button "Zapisz zamówienie"
"""


def test_the_mail_by_its_subject_the_reference_from_its_text_the_customer_by_its_name(
    tmp_path: Path,
) -> None:
    (tmp_path / "maile.csv").write_text("Temat;Uwagi\nZamówienie PO-10001;\n", encoding="utf-8")
    r = Recording()
    listed = r.state(MAIL, inbox(False))
    opened = r.state(MAIL, inbox(True))
    r.add("navigate", MAIL, value=MAIL, state_after=listed)
    cells = {"#1": f"Dział zakupów, Firma {SUBJECTS[2]}"}
    subject = found_by_its_words(
        ElementInfo(
            tag="span",
            text=SUBJECTS[2],
            css="#rcmrowNDM0 > td:nth-of-type(2) > span:nth-of-type(4)",
            row=RowContext(table="Lista wiadomości e-mail", cells=cells),
        )
    )
    r.add("click", MAIL, target=subject, state_before=listed, state_after=opened)
    r.add("navigated", MAIL, state_before=listed, state_after=opened)  # the e-mail opens
    new = f"{ERP}/zamowienia/nowe"
    form = r.state(new, ORDER)
    r.add("navigate", new, value=new, state_before=opened, state_after=form)
    customer = found_by_its_words(ElementInfo(tag="select", role="combobox", name="Klient"))
    r.add("select", new, target=customer, value="K0013", state_before=form,
          option_label="Sklep internetowy Grądziel-Lew (K0013)")  # fmt: skip
    r.add("fill", new, target=field("Numer referencyjny klienta"), value="PO-10001",
          state_before=form)  # fmt: skip
    save = found_by_its_words(ElementInfo(tag="button", role="button", name="Zapisz zamówienie"))
    r.add("click", new, target=save, state_before=form, state_after=form, sent=["POST /z"])
    model = map_trace(r.trace(tmp_path / "trace.jsonl", DataRef(file="maile.csv"))).model

    opening = next(s for s in model.steps if s.target and s.target[0].text)
    assert opening.target is not None
    assert opening.target[0].text == "{inputs.temat}"  # the e-mail the sheet names
    assert opening.within is None
    reads = {s.save_as: s for s in model.steps if s.action.value == "read"}
    customer_step = next(s for s in model.steps if s.action.value == "select_option")
    assert customer_step.match == "words"
    assert customer_step.value is not None
    text = reads[str(customer_step.value).removeprefix("$vars.")]
    assert text.target is not None
    assert text.target[0].model_dump(exclude_none=True) == {
        "role": "region",
        "name": "Treść wiadomości",
    }
    reference = next(s for s in model.steps if s.action.value == "fill")
    lead = reads[str(reference.value).removeprefix("$vars.")]
    assert lead.after == "realizację zamówienia nr"  # not „Zamówienie”: the inbox lists more
    assert set(model.inputs) == {"temat"}
