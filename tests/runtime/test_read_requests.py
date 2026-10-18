"""Only the confirmed form operation may pass the write guard."""

import pytest
from pydantic import ValidationError

from maptelo.model.schema import ReadRequest
from maptelo.sends import confirmed_read


@pytest.mark.parametrize(
    ("method", "url", "content_type", "body", "matches"),
    [
        (
            "POST",
            "https://app/form",
            "application/x-www-form-urlencoded",
            "action=preview&item=A",
            True,
        ),
        (
            "POST",
            "https://app/form",
            "application/x-www-form-urlencoded; charset=UTF-8",
            "action=preview&selected=A&selected=B",
            True,
        ),
        ("POST", "https://app/form", "application/x-www-form-urlencoded", "action=save", False),
        (
            "POST",
            "https://app/form",
            "application/x-www-form-urlencoded",
            "action=preview&action=save",
            False,
        ),
        (
            "POST",
            "https://app/form",
            "application/x-www-form-urlencoded",
            "action=preview&action=preview",
            False,
        ),
        (
            "POST",
            "https://other/form",
            "application/x-www-form-urlencoded",
            "action=preview",
            False,
        ),
        ("POST", "http://app/form", "application/x-www-form-urlencoded", "action=preview", False),
        ("POST", "https://app/other", "application/x-www-form-urlencoded", "action=preview", False),
        (
            "POST",
            "https://app/form?action=save",
            "application/x-www-form-urlencoded",
            "action=preview",
            False,
        ),
        ("PUT", "https://app/form", "application/x-www-form-urlencoded", "action=preview", False),
        ("POST", "https://app/form", "application/json", '{"action":"preview"}', False),
        ("POST", "https://app/form", "application/x-www-form-urlencoded", None, False),
        (
            "POST",
            "https://app/form",
            "application/x-www-form-urlencoded",
            "action=preview&invalid",
            False,
        ),
    ],
)
def test_read_contract_checks_origin_path_encoding_and_unambiguous_operation(
    method, url, content_type, body, matches
):
    assert (
        confirmed_read(
            method, url, content_type, body, "https://app", "/form", {"action": "preview"}
        )
        is matches
    )


@pytest.mark.parametrize(
    "path",
    [
        "//other/form",
        "https://other/form",
        "/form?save=1",
        "/form#save",
        "/{inputs.path}",
        "/**",
        "/form\\save",
    ],
)
def test_read_contract_is_an_exact_path_on_the_main_application(path):
    with pytest.raises(ValidationError):
        ReadRequest(path=path, form={"action": "preview"})


@pytest.mark.parametrize("form", [{}, {"": "preview"}, {"action": ""}])
def test_read_contract_must_distinguish_the_operation(form):
    with pytest.raises(ValidationError):
        ReadRequest(path="/form", form=form)
