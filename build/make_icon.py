"""Draw the zxide application icon and write it out as .ico / .png.

The icon is generated rather than checked in as hand-drawn art so it can be
re-rendered at any size without a paint program: everything here is plain Pillow
geometry. It has to read at 16x16 on a taskbar as well as 256x256 in Explorer,
which is why the shapes are few and fat -- a dark IDE-style rounded tile, a big
developer prompt (``>_``) as the "this is a code tool" cue, and the four slanted
Sinclair rainbow stripes that say which machine it develops for.

Everything is drawn at 1024x1024 and downsampled with LANCZOS into each icon size;
drawing small directly gives ragged diagonals, drawing big and shrinking gives the
antialiasing for free.

Run it from anywhere:  python build/make_icon.py
Writes build/icon/zxide.ico (the Windows executable icon, all sizes in one file)
and build/icon/zxide.png (256x256, for Linux .desktop entries and the repo docs).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

#: Supersample resolution. Every coordinate below is in this space.
S = 1024

#: Icon sizes Windows picks between: 16/32/48 for shell chrome, 256 for the big view.
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

#: The tile: near-black with a cool cast, like a dark editor theme's background.
TILE = (18, 20, 27, 255)
TILE_EDGE = (48, 54, 68, 255)

#: The prompt glyph. Off-white so it doesn't vibrate against the dark tile.
PROMPT = (240, 243, 248, 255)

#: The caret/underscore, in the Spectrum's bright yellow -- the one warm accent.
CARET = (255, 214, 0, 255)

#: The Sinclair badge stripes, in ZX bright red/yellow/green/cyan order.
STRIPES = [(255, 0, 0, 255), (255, 216, 0, 255), (0, 214, 0, 255), (0, 214, 214, 255)]


def _rounded_tile(draw: ImageDraw.ImageDraw) -> None:
    """The background: a rounded square with a hairline lighter edge for definition."""
    draw.rounded_rectangle([28, 28, S - 28, S - 28], radius=200, fill=TILE, outline=TILE_EDGE, width=10)


def _stripes(draw: ImageDraw.ImageDraw) -> None:
    """The four slanted rainbow bars, tucked into the top-right corner of the tile.

    They are drawn as thick 45-degree lines and then clipped by compositing through
    the tile's own mask (see :func:`build`), so they follow the rounded corner instead
    of poking out of it."""
    for index, colour in enumerate(STRIPES):
        offset = index * 104
        draw.line([(S - 600 + offset, 10), (S - 190 + offset, 420)], fill=colour, width=66)


def _prompt(draw: ImageDraw.ImageDraw) -> None:
    """The ``>`` chevron and its underscore -- the universal "developer tool" mark."""
    draw.line([(300, 356), (534, 566), (300, 776)], fill=PROMPT, width=96, joint="curve")
    draw.rounded_rectangle([596, 716, 812, 792], radius=38, fill=CARET)


def build() -> Image.Image:
    """Render the full icon at supersample resolution and return it."""
    tile_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle([28, 28, S - 28, S - 28], radius=200, fill=255)

    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    _rounded_tile(draw)

    # Stripes go on their own layer so the tile mask can clip them to the rounded corner.
    stripe_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    _stripes(ImageDraw.Draw(stripe_layer))
    canvas = Image.composite(Image.alpha_composite(canvas, stripe_layer), canvas, tile_mask)

    _prompt(ImageDraw.Draw(canvas))
    return canvas


def main() -> int:
    out_dir = Path(__file__).resolve().parent / "icon"
    out_dir.mkdir(parents=True, exist_ok=True)

    art = build()
    sizes = [art.resize((size, size), Image.LANCZOS) for size in ICO_SIZES]

    # Pillow's ICO writer rescales from the image it is given; handing it the pre-resized
    # 256 keeps the largest entry sharp, and append_images supplies the smaller entries.
    sizes[-1].save(out_dir / "zxide.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=sizes[:-1])
    sizes[-1].save(out_dir / "zxide.png", format="PNG")

    print("wrote {0} and {1}".format(out_dir / "zxide.ico", out_dir / "zxide.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
