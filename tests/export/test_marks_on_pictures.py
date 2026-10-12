"""The frame around the element a step acts on, on that step's picture. A Java window's picture
is the window alone while the bridge tells places on the screen: the clean-Windows Lite test of
12.10 drew no frame around „Zapisz” in a dialog standing in the middle of the screen."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from maptelo.export.images import screenshots_for
from maptelo.model import ProcessModel
from maptelo.trace import ElementInfo
from maptelo.trace.schema import Trace, TraceEvent, TraceHeader, TraceState

RED = (220, 38, 38)
DIALOG = "java://srk/Nowa wersja ceny - *"


def recorded(folder: Path, origin: tuple[int, int] | None) -> Trace:
    (folder / "screens").mkdir(parents=True)
    Image.new("RGB", (400, 300), (240, 240, 240)).save(folder / "screens" / "s1.png")
    state = TraceState(
        id="s1",
        t=0,
        url=DIALOG,
        aria='- button "Zapisz"',
        screenshot="screens/s1.png",
        origin=origin,
    )
    on_screen = (500 + 300, 400 + 200, 60, 24)  # the dialog's corner at 500, 400
    button = ElementInfo(tag="java:push button", role="button", name="Zapisz", bbox=on_screen)
    click = TraceEvent(seq=1, t=1, type="click", url=DIALOG, target=button, state_before="s1")
    header = TraceHeader(
        recording_id="r1", started_at=datetime(2026, 10, 12, tzinfo=UTC), start_url="java://srk/"
    )
    return Trace(header=header, events=[click], states={"s1": state}, path=folder / "trace.jsonl")


def model() -> ProcessModel:
    application = {"name": "SRK", "kind": "java", "window": "SRK", "base_url": "java://srk"}
    step = {
        "id": "zapisz",
        "intent": "Kliknij „Zapisz”",
        "action": "click",
        "target": [{"role": "button", "name": "Zapisz"}],
    }
    return ProcessModel.model_validate(
        {
            "schema_version": "0.1",
            "id": "ceny",
            "version": 1,
            "title": "Ceny",
            "application": application,
            "steps": [step],
        }
    )


def framed(picture: Path) -> set[tuple[int, int]]:
    with Image.open(picture) as image:
        rgb = image.convert("RGB")
        return {
            (x, y)
            for x in range(rgb.width)
            for y in range(rgb.height)
            if all(abs(a - b) < 40 for a, b in zip(rgb.getpixel((x, y)), RED, strict=True))
        }


def test_a_window_away_from_the_corner_gets_its_frame(tmp_path: Path) -> None:
    trace = recorded(tmp_path / "rec", origin=(500, 400))
    out = tmp_path / "map"
    images = screenshots_for(model(), {"zapisz": (trace, [1])}, out)
    red = framed(out / images["zapisz"])
    assert red, "no frame on the picture"
    xs, ys = {x for x, _ in red}, {y for _, y in red}
    assert 290 <= min(xs) <= 300  # around the button at 300..360, 200..224 of the picture
    assert 360 <= max(xs) <= 370
    assert 190 <= min(ys) <= 200
    assert 224 <= max(ys) <= 234


def test_a_picture_without_its_place_keeps_the_places_as_they_are(tmp_path: Path) -> None:
    trace = recorded(tmp_path / "rec", origin=None)  # a browser's picture is its page
    out = tmp_path / "map"
    images = screenshots_for(model(), {"zapisz": (trace, [1])}, out)
    assert framed(out / images["zapisz"]) == set()  # the place is off this picture
