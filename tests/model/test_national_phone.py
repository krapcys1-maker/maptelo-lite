"""A phone number the sheet writes with its country's code is typed without it, when the
recordings did so (typed_as: national; WebArena-Verified 364)."""

from __future__ import annotations

import pytest

from maptelo.model.schema import InputSpec


@pytest.mark.parametrize(
    ("written", "typed"),
    [
        ("+1 2058812302", "2058812302"),
        ("+48 600-100-200", "600-100-200"),
        ("555-229-3326", "555-229-3326"),
        ("+12058812302", "+12058812302"),
    ],
)
def test_a_phone_number_is_typed_without_its_country_s_code(written: str, typed: str) -> None:
    spec = InputSpec(type="string", typed_as="national")
    assert spec.on_screen(written) == typed
