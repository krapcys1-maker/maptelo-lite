"""Screen texts and element ids. Layout 'b' simulates a UI redesign (drift); ``drifted``
makes any number of other layouts from a seed, for the lab."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Texts:
    customer: str
    cpn: str
    search: str
    not_found: str
    back: str
    table: str
    columns: tuple[tuple[str, str], ...]
    select: str
    current_price: str
    price: str
    valid_from: str
    save: str
    saved: str
    choose_version: str
    no_active: str
    confirm_title: str
    confirm: str
    cancel: str
    ids: dict[str, str]
    testids: bool
    form_first: bool


LAYOUTS: dict[str, Texts] = {
    "a": Texts(
        customer="Customer",
        cpn="CPN",
        search="Search",
        not_found="No product found for CPN {cpn}.",
        back="Back to search",
        table="Price versions",
        columns=(
            ("version", "Version"),
            ("price", "Price"),
            ("currency", "Currency"),
            ("valid_from", "Valid from"),
            ("valid_to", "Valid to"),
            ("status", "Status"),
            ("action", ""),
        ),
        select="Select",
        current_price="Current price",
        price="Price",
        valid_from="Valid from",
        save="Save",
        saved="Price saved (version {version}).",
        choose_version="Several price versions exist. Select the active one to change it.",
        no_active="This product has no active price version. Contact the pricing team.",
        confirm_title="Confirm price change",
        confirm="Confirm",
        cancel="Cancel",
        ids={"customer": "customer", "cpn": "cpn", "price": "price", "valid_from": "valid_from"},
        testids=True,
        form_first=False,
    ),
    "b": Texts(
        customer="Client",
        cpn="Customer part no.",
        search="Find",
        not_found="Nothing matches part number {cpn}.",
        back="New search",
        table="Pricing history",
        columns=(
            ("status", "State"),
            ("valid_from", "From"),
            ("valid_to", "Until"),
            ("price", "Amount"),
            ("currency", "Cur."),
            ("version", "Ver."),
            ("action", ""),
        ),
        select="Edit",
        current_price="Price now",
        price="New price",
        valid_from="Effective date",
        save="Apply changes",
        saved="Changes applied ({version}).",
        choose_version="Pick the row you want to change.",
        no_active="No price is in force for this item.",
        confirm_title="Large price change",
        confirm="Yes, apply",
        cancel="Go back",
        ids={
            "customer": "f-cust-01",
            "cpn": "f-part-02",
            "price": "f-amt-07",
            "valid_from": "f-eff-08",
        },
        testids=False,
        form_first=True,
    ),
}


# --- drift: a new layout from a seed, as an application update would bring ----------------

SYNONYMS: dict[str, tuple[str, ...]] = {
    "customer": ("Client", "Account", "Customer account"),
    "cpn": ("Customer part no.", "Part number", "Item code"),
    "search": ("Find", "Look up", "Search now"),
    "not_found": (
        "Nothing matches part number {cpn}.",
        "Part {cpn} was not found.",
        "No item {cpn} for this client.",
    ),
    "back": ("New search", "Back", "Return to search"),
    "table": ("Pricing history", "Price list", "Versions"),
    "select": ("Edit", "Choose", "Open"),
    "current_price": ("Price now", "Current amount", "In force"),
    "price": ("New price", "Amount", "Net price"),
    "valid_from": ("Effective date", "Start date", "From"),
    "save": ("Apply changes", "Store", "Save changes"),
    "saved": ("Changes applied ({version}).", "Stored as version {version}."),
    "choose_version": ("Pick the row you want to change.", "Choose which version to change."),
    "no_active": ("No price is in force for this item.", "Nothing is active for this product."),
    "confirm_title": ("Large price change", "Please confirm"),
    "confirm": ("Yes, apply", "OK", "Proceed"),
    "cancel": ("Go back", "No"),
}
COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "version": ("Ver.", "Rev."),
    "price": ("Amount", "Net"),
    "currency": ("Cur.", "CCY"),
    "valid_from": ("From", "Start"),
    "valid_to": ("Until", "End"),
    "status": ("State", "Active?"),
}


def drifted(seed: int, rate: float, base: Texts | None = None) -> tuple[Texts, list[str]]:
    """Layout 'a' changed the way updates change screens, each change with probability
    ``rate``: words, column headers and order, ids, test ids, where the form is; rarely an
    adversary: the price and date fields trade their labels. Same seed, same layout."""
    rng = random.Random(f"drift-{seed}")
    start = base or LAYOUTS["a"]
    values = {name: getattr(start, name) for name in SYNONYMS}
    changes: list[str] = []
    for name, options in SYNONYMS.items():
        if rng.random() < rate:
            values[name] = rng.choice(options)
            changes.append(f"text:{name}")
    columns = list(start.columns)
    if rng.random() < rate:
        columns = [(key, rng.choice(COLUMN_SYNONYMS.get(key, (head,)))) for key, head in columns]
        changes.append("columns:renamed")
    if rng.random() < rate:
        moving, action = columns[:-1], columns[-1]
        rng.shuffle(moving)
        columns = [*moving, action]
        changes.append("columns:reordered")
    ids = dict(start.ids)
    if rng.random() < rate:
        ids = {key: f"f-{rng.randrange(16**4):04x}" for key in ids}
        changes.append("ids:renamed")
    testids = start.testids
    if rng.random() < rate:
        testids = not testids
        changes.append("testids:" + ("on" if testids else "off"))
    form_first = start.form_first
    if rng.random() < rate:
        form_first = not form_first
        changes.append("form:moved")
    if rng.random() < rate / 4:  # the adversary: what reads "Price" is now the date field
        values["price"], values["valid_from"] = values["valid_from"], values["price"]
        ids["price"], ids["valid_from"] = ids["valid_from"], ids["price"]
        changes.append("fields:swapped")
    texts = Texts(**values, columns=tuple(columns), ids=ids, testids=testids, form_first=form_first)
    return texts, changes
