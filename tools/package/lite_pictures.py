"""Maptelo Lite's icon and its installer's pictures, drawn from the brand's own logo and fonts
(Studio's static folder) by Chromium, at the sizes Windows and Inno Setup ask for:

    python tools/package/lite_pictures.py      # writes installer/lite/

maptelo-lite.ico   the program's icon (its shortcuts, the installer, the uninstaller)
wizard-*.bmp       the installer's tall picture (Inno Setup's sizes for 100, 150, 200 %)
small-*.bmp        its small picture (the same)

The pictures are kept in the repository: making them needs a browser, building does not.
"""

from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "maptelo" / "studio" / "static"
OUT = ROOT / "installer" / "lite"

INK = "#232b32"
PAPER = "#fbf8f3"
TEAL = "#02b6c0"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
WIZARD = ((202, 386), (336, 643), (430, 824))
SMALL = (58, 97, 124)


def _mark() -> str:
    """The prism with its rays: the favicon's drawing, without its own <svg> element."""
    svg = (STATIC / "favicon.svg").read_text(encoding="utf-8")
    return re.sub(r"^.*?<svg[^>]*>|</svg>\s*$", "", svg, flags=re.S).strip()


def _logo(ink: str, gap: str) -> str:
    """The logo with its word, from Studio's page, its ink and gaps in the given colours."""
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    found = re.search(r"<svg [^>]*viewBox=\"0 0 953 226\".*?</svg>", page, re.S)
    assert found is not None, "the logo is no longer on Studio's page"
    return (
        found.group(0)
        .replace('class="ink"', f'fill="{ink}"')
        .replace('class="gap"', f'fill="{gap}"')
        .replace('aria-hidden="true" focusable="false"', "")
    )


def _fonts() -> str:
    faces = []
    for family, stem in (("Instrument Sans", "instrument-sans"), ("Fraunces", "fraunces")):
        for part, unicode_range in (("latin", "U+0000-00FF"), ("latin-ext", "U+0100-024F")):
            url = (STATIC / "fonts" / f"{stem}-{part}-wght-normal.woff2").as_uri()
            faces.append(
                f"@font-face {{ font-family: '{family}'; src: url('{url}') format('woff2'); "
                f"font-weight: 100 900; unicode-range: {unicode_range}; }}"
            )
    return "\n".join(faces)


def _tile(size: int) -> str:
    """The icon: the prism on a dark rounded tile, a little larger when the icon is small."""
    inner = 0.86 if size <= 24 else 0.8
    return f"""<div style="width:{size}px;height:{size}px;border-radius:{size * 0.22:.1f}px;
      background:{INK};display:grid;place-items:center">
      <svg viewBox="0 0 240 240" width="{size * inner:.1f}" height="{size * inner:.1f}">
        {_mark()}</svg></div>"""


def _wizard(width: int, height: int) -> str:
    unit = width / 202
    return f"""<div style="width:{width}px;height:{height}px;background:{INK};position:relative;
      overflow:hidden;font-family:'Instrument Sans',sans-serif">
      <div style="position:absolute;left:0;right:0;top:0;height:{4 * unit:.1f}px;display:flex">
        <span style="flex:1;background:#01687a"></span>
        <span style="flex:1;background:{TEAL}"></span>
        <span style="flex:1;background:#ee9f40"></span></div>
      <svg viewBox="0 0 240 240" width="{196 * unit:.1f}" height="{196 * unit:.1f}"
        style="position:absolute;left:{6 * unit:.1f}px;top:{70 * unit:.1f}px">{_mark()}</svg>
      <div style="position:absolute;left:{18 * unit:.1f}px;right:{18 * unit:.1f}px;
        top:{262 * unit:.1f}px">{_logo(PAPER, INK).replace("<svg ", '<svg width="100%" ', 1)}
        <div style="margin-top:{4 * unit:.1f}px;padding-left:{166 * unit * 40 / 150:.1f}px;
          color:{TEAL};font-weight:600;font-size:{166 * unit * 11.5 / 150:.1f}px;
          letter-spacing:0.14em">LITE</div>
      </div></div>"""


def _shot(page: Page, html: str, size: tuple[int, int], transparent: bool = False) -> Image.Image:
    page.set_viewport_size({"width": size[0], "height": size[1]})
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as file:
        file.write(
            f"<!doctype html><meta charset=utf-8><style>{_fonts()} html,body{{margin:0;"
            f"background:{'transparent' if transparent else '#ffffff'}}}</style>{html}"
        )
    page.goto(Path(file.name).as_uri())
    page.evaluate("document.fonts.ready")
    picture = Image.open(io.BytesIO(page.screenshot(omit_background=transparent)))
    Path(file.name).unlink()
    return picture.convert("RGBA" if transparent else "RGB")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page(device_scale_factor=1)
        icons = [_shot(page, _tile(size), (size, size), transparent=True) for size in ICON_SIZES]
        icons[-1].save(
            OUT / "maptelo-lite.ico",
            format="ICO",
            sizes=[(s, s) for s in ICON_SIZES],
            append_images=icons[:-1],
        )
        for width, height in WIZARD:
            _shot(page, _wizard(width, height), (width, height)).save(OUT / f"wizard-{width}.bmp")
        for size in SMALL:
            tile = f'<div style="padding:{size * 0.06:.1f}px">{_tile(round(size * 0.88))}</div>'
            _shot(page, tile, (size, size)).save(OUT / f"small-{size}.bmp")
        browser.close()
    for path in sorted(OUT.iterdir()):
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
