"""The picture of a step that opens a screen by its address is that screen. An application may
first ask to sign in (the person does, then it opens what was asked): the clean-Windows Lite
test of 12.10 showed the sign-in under "Open the Customer prices screen"."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from maptelo.export.images import screenshots_for
from maptelo.model import ProcessModel
from maptelo.trace.schema import Trace, TraceEvent, TraceHeader, TraceState

SIGN_IN = (200, 200, 200)
PRICES = (30, 90, 200)


def recorded(folder: Path) -> Trace:
    (folder / "screens").mkdir(parents=True)
    states = {}
    for number, (address, colour) in enumerate(
        (("http://erp.test/login?next=/pricing", SIGN_IN), ("http://erp.test/pricing", PRICES)),
        start=1,
    ):
        Image.new("RGB", (80, 60), colour).save(folder / "screens" / f"s{number}.png")
        states[f"s{number}"] = TraceState(
            id=f"s{number}", t=number, url=address, aria="", screenshot=f"screens/s{number}.png"
        )
    events = [
        TraceEvent(seq=1, t=0.5, type="navigate", url="http://erp.test/", state_after="s1"),
        TraceEvent(
            seq=2,
            t=1.5,
            type="navigated",
            url="http://erp.test/pricing",
            state_before="s1",
            state_after="s2",
        ),
    ]
    header = TraceHeader(
        recording_id="r1",
        started_at=datetime(2026, 10, 12, tzinfo=UTC),
        start_url="http://erp.test/",
    )
    return Trace(header=header, events=events, states=states, path=folder / "trace.jsonl")


def model(address: str) -> ProcessModel:
    step = {"id": "open", "intent": "Open the prices", "action": "navigate", "value": address}
    return ProcessModel.model_validate(
        {
            "schema_version": "0.1",
            "id": "prices",
            "version": 1,
            "title": "Prices",
            "application": {"name": "ERP", "kind": "web", "base_url": "http://erp.test"},
            "steps": [step],
        }
    )


def colour(picture: Path) -> tuple[int, int, int]:
    with Image.open(picture) as image:
        red, green, blue = image.convert("RGB").getpixel((40, 30))
        return red, green, blue


def near(a: tuple[int, int, int], b: tuple[int, int, int]) -> bool:
    return all(abs(x - y) < 12 for x, y in zip(a, b, strict=True))


def test_the_screen_asked_for_not_the_sign_in_before_it(tmp_path: Path) -> None:
    trace = recorded(tmp_path / "rec")
    images = screenshots_for(model("/pricing"), {"open": (trace, [1])}, tmp_path / "map")
    assert near(colour(tmp_path / "map" / images["open"]), PRICES)


def test_a_screen_never_reached_keeps_the_picture_there_is(tmp_path: Path) -> None:
    trace = recorded(tmp_path / "rec")
    images = screenshots_for(model("/orders"), {"open": (trace, [1])}, tmp_path / "map")
    assert near(colour(tmp_path / "map" / images["open"]), SIGN_IN)
