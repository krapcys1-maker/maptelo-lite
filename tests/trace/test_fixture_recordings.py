"""The committed MiniERP recordings are consistent with their ground truth."""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from maptelo.trace import load_trace
from minierp.scenarios import PROCESS, SCENARIO_PASSWORD, SCENARIOS, Scenario

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recordings" / PROCESS


def test_every_scenario_has_a_recording_and_ground_truth() -> None:
    cases = YAML(typ="safe", pure=True).load((FIXTURES / "cases.yaml").read_text(encoding="utf-8"))
    assert [c["id"] for c in cases["recordings"]] == [s.id for s in SCENARIOS]
    assert sorted(p.name for p in FIXTURES.iterdir() if p.is_dir()) == [s.id for s in SCENARIOS]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_recording_matches_its_scenario(scenario: Scenario) -> None:
    path = FIXTURES / scenario.id / "trace.jsonl"
    text = path.read_text(encoding="utf-8")
    assert SCENARIO_PASSWORD not in text
    trace = load_trace(path)
    assert trace.header.process == PROCESS
    assert trace.end is not None
    actions = trace.actions()
    assert actions[0].type == "navigate"
    assert all(a.state_after for a in actions), "every action has the screen state after it"
    fills = {a.target.name: a.value for a in actions if a.type == "fill" and a.target}
    assert fills.get("CPN") == scenario.cpn
    selects = [a for a in actions if a.type == "select"]
    assert selects[0].value == scenario.customer
    observed = [e.target.role for e in trace.events if e.type == "appeared" and e.target]
    if scenario.outcome == "saved":
        assert fills["Price"] == scenario.new_price
        assert fills["Valid from"] == scenario.valid_from
        assert "status" in observed
    if scenario.outcome == "not_found" or scenario.wrong_cpn_first:
        assert "alert" in observed
    if scenario.session_popup:
        assert "dialog" in observed
        continue_click = next(a for a in actions if a.target and a.target.name == "Continue")
        assert continue_click.target is not None
        assert continue_click.target.dialog == "Session expiring"
    if scenario.login:
        password = next(a for a in actions if a.target and a.target.name == "Password")
        assert password.secret
        assert password.value is None
