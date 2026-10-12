from __future__ import annotations

import json
from pathlib import Path

import pytest

from maptelo.capture import DevToolsImportError, import_devtools_file, redact_secrets
from maptelo.capture.devtools import convert
from maptelo.trace import TraceEvent, load_trace

DEVTOOLS = (
    Path(__file__).resolve().parents[1] / "fixtures" / "devtools" / "minierp-price-change.json"
)


def test_password_values_are_removed_from_snapshots() -> None:
    snapshot = '- textbox "Username": demo\n- textbox "Password": S3cret!x\n- text: S3cret!x'
    assert redact_secrets(snapshot, ["S3cret!x"]) == (
        '- textbox "Username": demo\n- textbox "Password": [redacted]\n- text: [redacted]'
    )


def test_short_secrets_are_only_removed_from_their_textbox() -> None:
    snapshot = '- textbox "PIN": 42\n- cell: "42"'
    assert redact_secrets(snapshot, ["42"]) == '- textbox "PIN": [redacted]\n- cell: "42"'


def test_no_secrets_no_change() -> None:
    assert redact_secrets("- main", []) == "- main"


def test_devtools_export_becomes_a_trace(tmp_path: Path) -> None:
    path = import_devtools_file(DEVTOOLS, tmp_path / "imported", process="update_customer_price")
    trace = load_trace(path)
    assert trace.header.source == "chrome-devtools-recorder"
    assert trace.header.viewport == (1280, 860)
    assert trace.header.start_url == "http://127.0.0.1:8701/pricing"
    assert [e.type for e in trace.actions()] == [
        "navigate", "fill", "click", "fill", "click", "click", "click", "fill", "fill", "press",
    ]  # fmt: skip
    customer = trace.actions()[1]
    assert customer.value == "C001"
    assert customer.target is not None
    assert [c.describe() for c in customer.target.candidates] == [
        'label="Customer"',
        'testid="customer-select"',
    ]
    search = trace.actions()[4]
    assert search.target is not None
    assert search.target.candidates[0].describe() == 'role=button name="Search"'
    assert [e.url for e in trace.events if e.type == "navigated"][-1].endswith("?saved=V4")


def test_devtools_import_rejects_other_json(tmp_path: Path) -> None:
    with pytest.raises(DevToolsImportError, match="'steps' is missing"):
        convert({"hello": "world"}, recording_id="x")
    with pytest.raises(DevToolsImportError, match="no navigate step"):
        convert({"steps": [{"type": "click", "selectors": [["#a"]]}]}, recording_id="x")
    with pytest.raises(DevToolsImportError, match="no usable selector"):
        convert(
            {
                "steps": [
                    {"type": "navigate", "url": "http://a"},
                    {"type": "click", "selectors": []},
                ]
            },
            recording_id="x",
        )
    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    with pytest.raises(DevToolsImportError, match="not valid JSON"):
        import_devtools_file(broken, tmp_path / "out")


def test_devtools_steps_keep_their_order() -> None:
    flow = json.loads(DEVTOOLS.read_text(encoding="utf-8"))
    records = convert(flow, recording_id="x")
    events = [r for r in records if isinstance(r, TraceEvent)]
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
