from __future__ import annotations

import json
from pathlib import Path

import pytest

from maptelo.model import ModelLoadError, json_schema, lint, load_model, parse_model
from maptelo.model.loader import _yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = sorted((ROOT / "examples").glob("*.yaml"))
SCHEMA_FILE = ROOT / "schemas" / "process-model-0.1.schema.json"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_are_valid_and_clean(path: Path) -> None:
    model = load_model(path)
    assert lint(model) == []


def test_example_price_update_shape() -> None:
    model = load_model(ROOT / "examples" / "update_customer_price.yaml")
    assert set(model.inputs) == {"customer", "cpn", "new_price", "valid_from"}
    assert model.step("pick_active_version").within is not None
    assert model.step("check_result").verify_effects == ["price_set"]


def test_yaml_is_read_as_yaml_1_2() -> None:
    # In YAML 1.1 (PyYAML) these would silently turn into booleans.
    assert _yaml().load("a: on\nb: no\nc: yes") == {"a": "on", "b": "no", "c": "yes"}


def test_a_written_model_always_reads_back() -> None:
    """Values that begin with a colon (":30", "::1", "://" from a recording without a host)
    were written plain inside one-line mappings, and the model then failed to load."""
    from maptelo.model import dump_model

    text = """
schema_version: "0.1"
id: demo
version: 1
title: Demo
application: {name: App, base_url: "://"}
inputs:
  minutes: {type: string, example: ":30"}
steps:
  - {id: open, intent: Open, action: navigate, value: /}
  - {id: host, intent: Host, action: fill, target: {label: Host}, value: "::1"}
  - {id: wait, intent: Wait, action: fill, target: {label: Note}, value: "a: b #c"}
"""
    model = parse_model(text)
    again = parse_model(dump_model(model), "written")
    assert again == model
    assert again.application.base_url == "://"
    assert again.inputs["minutes"].example == ":30"


def test_duplicate_keys_are_rejected() -> None:
    with pytest.raises(ModelLoadError, match="invalid YAML"):
        parse_model("id: a\nid: b\n")


def test_top_level_must_be_a_mapping() -> None:
    with pytest.raises(ModelLoadError, match="mapping at the top level"):
        parse_model("- just\n- a list\n")


def test_errors_point_to_the_broken_place() -> None:
    text = """
schema_version: "0.1"
id: demo
version: 1
title: Demo
application: {name: App}
steps:
  - {id: open, intent: Open, action: navigate, value: /}
  - {id: save, intent: Save, action: click}
"""
    with pytest.raises(ModelLoadError) as caught:
        parse_model(text, "demo.yaml")
    assert caught.value.problems == ["steps[1]: action 'click' requires 'target'"]


def test_committed_json_schema_is_current() -> None:
    expected = json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"
    assert SCHEMA_FILE.read_text(encoding="utf-8") == expected, (
        "Regenerate it: uv run maptelo model schema --out schemas/process-model-0.1.schema.json"
    )
