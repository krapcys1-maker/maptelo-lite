"""A screen whose title and heading are the record's value is one screen for every record:
the value is marked in any letters and with the shop's ® or ™ (the sheet's „teton pullover
hoodie” is the product page „Teton Pullover Hoodie®”, WebArena-Verified 242)."""

from __future__ import annotations

from maptelo.mapping import map_trace
from maptelo.trace import ElementInfo
from tests.mapping.test_many_apps import Recording, found_by_its_words

SHOP = "http://shop.test"


def test_the_product_page_is_named_by_the_record_s_value_in_any_letters() -> None:
    r = Recording()
    grid = r.state(f"{SHOP}/products", '- textbox "Search by keyword"\n- link "Edit"\n')
    page = r.state(f"{SHOP}/products/edit/17", '- heading "Teton Pullover Hoodie®" [level=1]\n')
    search = found_by_its_words(ElementInfo(tag="input", role="textbox", name="Search by keyword"))
    edit = found_by_its_words(ElementInfo(tag="a", role="link", name="Edit"))
    r.add("navigate", f"{SHOP}/products", value=f"{SHOP}/products", state_after=grid)
    r.add(
        "fill",
        f"{SHOP}/products",
        target=search,
        value="teton pullover hoodie",
        state_before=grid,
    )
    r.add("click", f"{SHOP}/products", target=edit, state_before=grid, state_after=page)
    r.add(
        "navigated",
        f"{SHOP}/products/edit/17",
        title="Teton Pullover Hoodie® / Products / Magento Admin",
        state_before=grid,
        state_after=page,
    )
    model = map_trace(r.trace(), lang="en").model
    shown = [
        rung.model_dump(exclude_none=True)
        for state in model.states.values()
        for rung in state.visible or []
    ]
    name = next(iter(model.inputs))
    assert {"role": "heading", "name": "{inputs." + name + "}"} in shown
