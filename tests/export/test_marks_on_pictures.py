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


def recorded(folder: Path, origin: tuple[int, int] | None, scale: float | None = None) -> Trace:
    (folder / "screens").mkdir(parents=True)
    Image.new("RGB", (400, 300), (240, 240, 240)).save(folder / "screens" / "s1.png")
    state = TraceState(
        id="s1",
        t=0,
        url=DIALOG,
        aria='- button "Zapisz"',
        screenshot="screens/s1.png",
        origin=origin,
        scale=scale,
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


def test_a_picture_of_a_scaled_display_frames_the_element_where_it_is(tmp_path: Path) -> None:
    """A display at 125 %: the bridge tells the button at 800, 600 in the screen's pixels, the
    picture is in the scaled ones (0.8 of a pixel each): the button is at 240..288, 160..179."""
    trace = recorded(tmp_path / "rec", origin=(500, 400), scale=0.8)
    out = tmp_path / "map"
    images = screenshots_for(model(), {"zapisz": (trace, [1])}, out)
    red = framed(out / images["zapisz"])
    xs, ys = {x for x, _ in red}, {y for _, y in red}
    assert 230 <= min(xs) <= 240
    assert 288 <= max(xs) <= 298
    assert 150 <= min(ys) <= 160
    assert 179 <= max(ys) <= 189


def test_the_picture_s_place_says_when_the_display_is_scaled() -> None:
    """The place of a window as the bridge tells it, against its picture's as Windows tells
    Maptelo: the clean-Windows Lite test of 12.10 (125 %, SRK's dialog „Nowa wersja ceny”)."""
    from maptelo.capture.java import picture_place

    assert picture_place((550, 241, 838, 539), (433, 192), (670, 431)) == ((550, 241), 0.7995)
    assert picture_place((-8, -8, 1936, 1056), (-8, -8), (1936, 1056)) == ((-8, -8), None)
    assert picture_place((10, 10, 800, 600), (9, 9), (802, 601)) == ((9, 9), None)  # a border
    assert picture_place((0, 0, 0, 0), (5, 5), (100, 100)) == ((5, 5), None)  # not told


def test_a_window_s_picture_leaves_out_its_invisible_borders() -> None:
    """Windows counts invisible resize borders into a window's rectangle and its picture shows
    them black (the clean-Windows Lite film of 12.10, 125 %: SRK's question with black bars
    left, right and below); the frame DWM draws is a few pixels inside. A rectangle in other
    pixels than DWM's (a program that does not know the display is scaled) leaves nothing out."""
    from maptelo.capture.java import visible_inset

    assert visible_inset((1081, 575, 1472, 816), (1090, 575, 1463, 807)) == (9, 0, 9, 9)
    assert visible_inset((-11, -11, 1931, 1051), (0, 0, 1920, 1040)) == (11, 11, 11, 11)
    assert visible_inset((865, 460, 1178, 653), (1081, 575, 1472, 816)) == (0, 0, 0, 0)
    assert visible_inset((0, 0, 400, 300), (0, 0, 400, 300)) == (0, 0, 0, 0)
    assert visible_inset((0, 0, 400, 300), (10, 10, 10, 10)) == (0, 0, 0, 0)  # no frame
