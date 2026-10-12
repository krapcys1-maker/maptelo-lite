"""A button's name in older recordings (benchmark p02): when different buttons share it, it is
not what finds them."""

from __future__ import annotations

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo
from maptelo.trace.locators import candidates_for
from tests.mapping.test_normalize import URL, Builder, field


def button(name: str, action: str) -> ElementInfo:
    info = ElementInfo(tag="button", role="button", name=name, text=name, action=action)
    return info.model_copy(update={"candidates": candidates_for(info)})


def test_a_name_different_buttons_share_is_forgotten() -> None:
    b = Builder()
    b.add("navigate", value=URL)
    product = field("Produkt")
    product = product.model_copy(update={"candidates": candidates_for(product)})
    b.add("fill", target=product, value="43871-B")
    b.add("click", target=button("Dodaj pozycję", "action"))
    b.add("click", target=button("Zapisz zamówienie", "action"))
    steps = map_trace(b.trace(), lang="en").model.steps
    rungs = [rung for step in steps for rung in step.target or []]
    assert all(rung.action is None for rung in rungs)
    assert {"role": "button", "name": "Zapisz zamówienie"} in [
        rung.model_dump(exclude_none=True) for rung in rungs
    ]


def test_a_name_only_one_button_has_is_kept() -> None:
    """Odoo's business buttons: action_confirm says what the button does, in any words."""
    b = Builder()
    b.add("navigate", value=URL)
    b.add("click", target=button("Potwierdź", "action_confirm"))
    b.add("click", target=button("Wyślij", "action_quotation_send"))
    steps = map_trace(b.trace(), lang="en").model.steps
    actions = [rung.action for step in steps for rung in step.target or [] if rung.action]
    assert actions == ["action_confirm", "action_quotation_send"]
