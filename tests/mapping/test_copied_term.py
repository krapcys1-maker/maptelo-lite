"""A value that says little on its own („Czynny”, „25”) copied from another screen: it is read
from under the field's own name — a term's definition (a register shows „Status VAT”:
„Czynny”) — and never from any other place that happens to say the same word."""

from __future__ import annotations

from maptelo.mapping import map_trace
from tests.mapping.test_many_apps import ERP, Recording, field

REGISTER = "http://wykaz.test/podmiot/5260250274"
FORM = f"{ERP}/dostawcy/nowy"


def register(term: str) -> str:
    return (
        '- heading "Wykaz podatników VAT" [level=1]\n'
        f"- term: {term}\n"
        "- definition: Czynny\n"
        "- term: Nazwa\n"
        "- definition: Hurtownia Brzozowska sp. z o.o.\n"
    )


FORM_ARIA = '- heading "Nowy dostawca" [level=1]\n- textbox "Status VAT"\n'


def mapped(term: str) -> list[dict[str, object]]:
    r = Recording()
    shown = r.state(REGISTER, register(term))
    r.add("navigate", REGISTER, value=REGISTER, state_after=shown)
    form = r.state(FORM, FORM_ARIA)
    r.add("navigate", FORM, value=FORM, state_before=shown, state_after=form)
    r.add("fill", FORM, target=field("Status VAT"), value="Czynny", state_before=form)
    model = map_trace(r.trace()).model
    return [s.model_dump(exclude_none=True, mode="json") for s in model.steps]


def test_a_plain_word_under_the_fields_own_term_is_read_from_there() -> None:
    steps = mapped("Status VAT")
    read = next(s for s in steps if s["action"] == "read")
    fill = next(s for s in steps if s["action"] == "fill")
    assert fill["value"] == f"$vars.{read['save_as']}"


def test_a_plain_word_under_another_term_is_not_taken_for_the_copy() -> None:
    steps = mapped("Status podatnika")
    assert not any(s["action"] == "read" for s in steps)
