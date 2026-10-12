from __future__ import annotations

from datetime import UTC, datetime

from maptelo.trace import (
    ElementInfo,
    RowContext,
    Trace,
    TraceEvent,
    TraceHeader,
    candidates_for,
    describe_event,
    summarize,
)


def test_ladder_prefers_accessibility_then_label_testid_text_css() -> None:
    element = ElementInfo(
        tag="button",
        role="button",
        name="Save",
        testid="save-button",
        text="Save",
        css="#main > form > button",
    )
    assert [c.describe() for c in candidates_for(element)] == [
        'role=button name="Save"',
        'testid="save-button"',
        'text="Save"',
        'css="#main > form > button"',
    ]


def test_ladder_skips_weak_roles_and_duplicates() -> None:
    element = ElementInfo(tag="td", role="cell", name="V3", text="V3", css="td")
    assert [c.describe() for c in candidates_for(element)] == ['css="td"']
    field = ElementInfo(tag="input", role="textbox", name="Price", label="Price", css="#price")
    assert [c.describe() for c in candidates_for(field)] == [
        'role=textbox name="Price"',
        'label="Price"',
        'css="#price"',
    ]


def test_describe_events() -> None:
    row = RowContext(table="Price versions", cells={"Version": "V3", "Status": "Active", "#7": ""})
    link = ElementInfo(tag="a", role="link", name="Select", row=row)
    click = TraceEvent(seq=4, t=2, type="click", target=link)
    assert describe_event(click) == 'click link "Select"  [row: Version=V3, Status=Active]'

    secret = TraceEvent(
        seq=2,
        t=1,
        type="fill",
        target=ElementInfo(tag="input", role="textbox", name="Password"),
        secret=True,
    )
    assert describe_event(secret) == 'fill textbox "Password" = *** (secret)'

    popup = ElementInfo(tag="div", role="dialog", name="Session expiring", text="Stay signed in?")
    appeared = TraceEvent(seq=5, t=3, type="appeared", target=popup)
    assert describe_event(appeared) == 'appeared dialog "Session expiring": Stay signed in?'


def test_summary_counts_actions_and_observations() -> None:
    trace = Trace(
        header=TraceHeader(
            recording_id="r1",
            started_at=datetime(2026, 10, 7, tzinfo=UTC),
            start_url="http://app/pricing",
            process="update_customer_price",
        ),
        events=[
            TraceEvent(seq=1, t=0, type="navigate", value="http://app/pricing"),
            TraceEvent(seq=2, t=1, type="navigated", url="http://app/pricing/product/C001"),
        ],
    )
    text = summarize(trace)
    assert "update_customer_price" in text
    assert "open /pricing" in text
    assert "-> /pricing/product/C001" in text
    assert text.endswith("1 actions, 1 observations, 0 states")
