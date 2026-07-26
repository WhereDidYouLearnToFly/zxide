"""The native sprite formats -- for sprites drawn in zxide, not imported from artwork.

An imported sprite's source of truth is a BMP file, which makes sense for artwork that
already exists (or that you'd rather draw in a real paint program) -- but a sprite
created *from scratch* in zxide's own pixel editor has no such file to begin with, and
routing every keystroke through BMP encode/decode would be needless overhead for data
the editor already holds as plain pixels and attributes.

So a native sprite file **is** the bytes a Z80 program gets. No container, no encoding
step at build time: what the editor writes is what ``incbin`` pulls in. The extension
says everything needed to read the file back, along two axes -- how the frame size is
known, and whether the sprite carries colour:

    hero.zx8x8         8x8 frames,  pixels + one attribute byte per 8x8 cell
    hero.zx16x16      16x16 frames, pixels + attributes
    hero.zxsprite     any size,     pixels + attributes; **byte 0 = width, byte 1 = height**
    hero.zx8x8pix      8x8 frames,  pixels only
    hero.zx16x16pix   16x16 frames, pixels only
    hero.zxspritepix  any size,     pixels only; same two-byte width/height header

The two fixed sizes carry no header at all: the extension already says the size, so
spending two bytes to repeat it would be dead weight in a format whose whole point is
that it needs no unpacking. The ``.zxsprite`` pair is the arbitrary-size case, where
nothing else could tell you the dimensions, so there the header earns its place.

The ``…pix`` variants exist because a great many sprites are drawn once and coloured by
the code that plots them -- a monochrome ship, a font-like glyph, a mask. For those, an
attribute plane is bytes of nothing, and on a 48K that is not a rounding error. The
editor drops to black-and-white when it opens one, since there is no colour to edit.

Each frame is laid out the way a :class:`~zxemu_core.assets.manifest.FrameSequence` lays
one out -- the packed 1bpp pixel plane (``width/8 * height`` bytes, row-major,
MSB-first), then, for the attributed formats, one real Spectrum attribute byte per 8x8
cell:

    8x8   frame =  8 pixel bytes + 1 attribute byte  =  9 bytes  (.zx8x8)
    8x8   frame =  8 pixel bytes                     =  8 bytes  (.zx8x8pix)
    16x16 frame = 32 pixel bytes + 4 attribute bytes = 36 bytes  (.zx16x16)

Frame *count* isn't stored: it follows from the file's length divided by the frame
stride, which keeps every number in the file a number the Z80 actually needs.

Deliberately no mask plane (v1 -- hand-drawn sprites can add transparency later the
same way ``generate_mask`` was added to the BMP path, by extending the stride).

The older ``.zxspr.json`` shape that shipped first is still read (see
``parse_native_sprite``) so projects created before these formats exist keep building;
nothing writes it any more.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from zxemu_core.assets.manifest import FrameSequence

# --- the extensions -----------------------------------------------------------------

SUFFIX_8X8 = ".zx8x8"
SUFFIX_16X16 = ".zx16x16"
SUFFIX_SPRITE = ".zxsprite"
SUFFIX_8X8_PIX = ".zx8x8pix"
SUFFIX_16X16_PIX = ".zx16x16pix"
SUFFIX_SPRITE_PIX = ".zxspritepix"
LEGACY_JSON_SUFFIX = ".zxspr.json"

HEADER_BYTES = 2  # width, height -- only on the arbitrary-size formats

DEFAULT_INK = 0
DEFAULT_PAPER = 7

MAX_DIMENSION = 255  # width/height are one byte each in a size header


@dataclass(frozen=True)
class SpriteFormat:
    """What one native sprite extension means: frame size, and whether colour is stored.

    ``size`` of None is the arbitrary-size case -- those files open with a two-byte
    width/height header instead. Every decision that differs between the six extensions
    is one of these two fields, which is why reading a file is a table lookup rather
    than a chain of suffix tests scattered through the codebase.
    """

    suffix: str
    size: tuple[int, int] | None
    has_attrs: bool

    @property
    def has_header(self) -> bool:
        return self.size is None


SPRITE_FORMATS: dict[str, SpriteFormat] = {
    fmt.suffix: fmt
    for fmt in (
        SpriteFormat(SUFFIX_8X8, (8, 8), has_attrs=True),
        SpriteFormat(SUFFIX_16X16, (16, 16), has_attrs=True),
        SpriteFormat(SUFFIX_SPRITE, None, has_attrs=True),
        SpriteFormat(SUFFIX_8X8_PIX, (8, 8), has_attrs=False),
        SpriteFormat(SUFFIX_16X16_PIX, (16, 16), has_attrs=False),
        SpriteFormat(SUFFIX_SPRITE_PIX, None, has_attrs=False),
    )
}

# Longest-first, so a suffix that is a tail of another can never shadow it.
SPRITE_SUFFIXES: tuple[str, ...] = tuple(
    sorted([*SPRITE_FORMATS, LEGACY_JSON_SUFFIX], key=len, reverse=True)
)


def sprite_suffix(filename: str) -> str | None:
    """Which native sprite suffix ``filename`` ends with, or None if it isn't one."""
    lowered = filename.lower()
    return next((suffix for suffix in SPRITE_SUFFIXES if lowered.endswith(suffix)), None)


def sprite_format(filename: str) -> SpriteFormat | None:
    """The :class:`SpriteFormat` for ``filename``, or None (including for legacy JSON)."""
    return SPRITE_FORMATS.get(sprite_suffix(filename) or "")


def suffix_for(width: int, height: int, has_attrs: bool) -> str:
    """The extension a sprite of this size and colour-ness should be saved under.

    A new 8x8 or 16x16 sprite gets the self-describing extension rather than an
    arbitrary-size file with a redundant header -- that choice belongs here, next to the
    table that gives the suffixes their meaning, not in whichever menu command happens
    to be creating the file.
    """
    for fmt in SPRITE_FORMATS.values():
        if fmt.size == (width, height) and fmt.has_attrs == has_attrs:
            return fmt.suffix
    return SUFFIX_SPRITE if has_attrs else SUFFIX_SPRITE_PIX


# --- attribute bytes -----------------------------------------------------------------


def attr_byte(ink: int, paper: int, bright: bool) -> int:
    """ink/paper/bright -> the real Spectrum attribute byte the file stores."""
    if not (0 <= ink <= 7 and 0 <= paper <= 7):
        raise ValueError("ink/paper must be 0-7, got ink={} paper={}".format(ink, paper))
    return ((1 if bright else 0) << 6) | (paper << 3) | ink


def attr_parts(byte: int) -> tuple[int, int, bool]:
    """The inverse of :func:`attr_byte` -- ``(ink, paper, bright)``."""
    return byte & 0x07, (byte >> 3) & 0x07, bool(byte & 0x40)


DEFAULT_ATTR = attr_byte(DEFAULT_INK, DEFAULT_PAPER, False)

# What a pixel-only sprite is shown as: white ink on black paper. Nothing in the file
# says this -- there is no attribute plane -- so it is a display choice, and this is the
# one that reads as "black and white" rather than as some particular colour scheme.
MONO_ATTR = attr_byte(7, 0, False)


# --- the in-memory document ----------------------------------------------------------


@dataclass
class SpriteFrame:
    """One frame: a pixel grid, and one attribute byte per 8x8 cell if the format has them.

    ``pixels`` is one row per ``y``, holding 0/1 per ``x`` -- unpacked on purpose. The
    editor pokes single pixels constantly, and doing that against packed bytes would mean
    a shift-and-mask on every click for no gain on data this small; packing happens once,
    in :meth:`SpriteDocument.encode`. ``attrs`` is empty for a pixel-only sprite.
    """

    pixels: list[bytearray]
    attrs: list[int] = field(default_factory=list)


@dataclass
class SpriteDocument:
    """A whole native sprite: a frame size, whether it stores colour, and the frames."""

    width: int
    height: int
    frames: list[SpriteFrame]
    has_attrs: bool = True

    def __post_init__(self) -> None:
        if self.width % 8 != 0 or self.height % 8 != 0:
            raise ValueError("sprite size must be a multiple of 8 in both dimensions, got {}x{}".format(self.width, self.height))
        if not 8 <= self.width <= MAX_DIMENSION or not 8 <= self.height <= MAX_DIMENSION:
            raise ValueError("sprite size must be 8..{}, got {}x{}".format(MAX_DIMENSION, self.width, self.height))

    @property
    def bytes_per_row(self) -> int:
        return self.width // 8

    @property
    def attr_cols(self) -> int:
        return self.width // 8

    @property
    def attr_rows(self) -> int:
        return self.height // 8

    @property
    def plane_bytes(self) -> int:
        return self.bytes_per_row * self.height

    @property
    def attr_plane_bytes(self) -> int:
        return self.attr_cols * self.attr_rows if self.has_attrs else 0

    @property
    def frame_stride(self) -> int:
        return self.plane_bytes + self.attr_plane_bytes

    def cell_index(self, x: int, y: int) -> int:
        """Which attribute cell the pixel at (x, y) belongs to."""
        return (y // 8) * self.attr_cols + (x // 8)

    def cell_attr(self, frame_index: int, cell: int) -> int:
        """A cell's attribute byte -- the mono stand-in for a pixel-only sprite."""
        if not self.has_attrs:
            return MONO_ATTR
        return self.frames[frame_index].attrs[cell]

    def encode(self, *, with_header: bool) -> bytes:
        """The file's bytes: the optional size header, then every frame back to back."""
        out = bytearray()
        if with_header:
            out += bytes([self.width, self.height])
        for frame in self.frames:
            for row in frame.pixels:
                for byte_col in range(self.bytes_per_row):
                    packed = 0
                    for bit in range(8):
                        if row[byte_col * 8 + bit]:
                            packed |= 0x80 >> bit
                    out.append(packed)
            if self.has_attrs:
                out += bytes(frame.attrs)
        return bytes(out)

    def to_frame_sequence(self, *, with_header: bool = False) -> FrameSequence:
        """This document as the shape the build/preview pipeline consumes.

        The header never enters ``data``: a ``FrameSequence``'s consumers index frames by
        ``frame_stride`` from byte zero, and shifting that by two for one source format
        would break every one of them. It rides along in ``header`` instead, which only
        the build reads, when it writes the blob the assembler includes.
        """
        return FrameSequence(
            frame_width=self.width,
            frame_height=self.height,
            frame_count=len(self.frames),
            has_mask=False,
            data=self.encode(with_header=False),
            has_attrs=self.has_attrs,
            header=bytes([self.width, self.height]) if with_header else b"",
        )


def blank_sprite(width: int, height: int, frame_count: int = 1, has_attrs: bool = True) -> SpriteDocument:
    """A fresh, all-paper sprite -- what "New Sprite Asset" writes to disk."""
    return SpriteDocument(
        width=width,
        height=height,
        frames=[_blank_frame(width, height, has_attrs) for _ in range(frame_count)],
        has_attrs=has_attrs,
    )


def _blank_frame(width: int, height: int, has_attrs: bool) -> SpriteFrame:
    cells = (width // 8) * (height // 8)
    return SpriteFrame(
        pixels=[bytearray(width) for _ in range(height)],
        attrs=[DEFAULT_ATTR] * cells if has_attrs else [],
    )


# --- decoding ------------------------------------------------------------------------


def decode_sprite(data: bytes, fmt: SpriteFormat) -> SpriteDocument:
    """Raw file bytes -> a :class:`SpriteDocument`, read the way ``fmt`` says to."""
    body = data
    if fmt.has_header:
        if len(data) < HEADER_BYTES:
            raise ValueError("sprite file is {} bytes -- too short for its width/height header".format(len(data)))
        width, height, body = data[0], data[1], data[HEADER_BYTES:]
    else:
        width, height = fmt.size  # type: ignore[misc]  # a fixed-size format always has one

    document = SpriteDocument(width=width, height=height, frames=[], has_attrs=fmt.has_attrs)
    stride = document.frame_stride
    if not body:
        raise ValueError("sprite file contains no frames")
    if len(body) % stride != 0:
        raise ValueError(
            "sprite body is {} bytes, not a whole number of {}x{} frames ({} bytes each)".format(len(body), width, height, stride)
        )

    for start in range(0, len(body), stride):
        frame_bytes = body[start : start + stride]
        pixels = []
        for row_index in range(height):
            row = bytearray(width)
            row_start = row_index * document.bytes_per_row
            for byte_col in range(document.bytes_per_row):
                packed = frame_bytes[row_start + byte_col]
                for bit in range(8):
                    row[byte_col * 8 + bit] = 1 if packed & (0x80 >> bit) else 0
            pixels.append(row)
        attrs = list(frame_bytes[document.plane_bytes :]) if fmt.has_attrs else []
        document.frames.append(SpriteFrame(pixels=pixels, attrs=attrs))
    return document


def load_sprite_file(filename: str, data: bytes) -> SpriteDocument:
    """Read any native sprite file -- the one entry point callers should use.

    ``filename`` decides how to read ``data``: which frame size, whether to expect a
    header, whether there is an attribute plane -- or, for the legacy ``.zxspr.json``
    shape, that it isn't binary at all.
    """
    suffix = sprite_suffix(filename)
    if suffix is None:
        raise ValueError("{!r} is not a native sprite file (expected one of {})".format(filename, ', '.join(SPRITE_SUFFIXES)))
    if suffix == LEGACY_JSON_SUFFIX:
        return _document_from_legacy_json(json.loads(data.decode("utf-8")))
    return decode_sprite(data, SPRITE_FORMATS[suffix])


def convert_sprite_file(filename: str, data: bytes) -> FrameSequence:
    """Any native sprite file -> the :class:`FrameSequence` the build wants.

    The single call the asset registry makes, so "which extensions are sprites, and
    which of them carry a header" stays a fact of this module alone.
    """
    fmt = sprite_format(filename)
    return load_sprite_file(filename, data).to_frame_sequence(with_header=bool(fmt and fmt.has_header))


# --- the legacy .zxspr.json shape ----------------------------------------------------
#
# The first version of the native format: JSON, with pixels as one '#'/'.' string per
# row and attributes as {ink, paper, bright} dicts. Read-only now -- kept so a project
# authored before the binary formats existed still opens and still builds.


def blank_sprite_data(frame_width: int, frame_height: int, frame_count: int = 1) -> dict:
    """A blank sprite in the legacy JSON shape (kept for tests and migration only)."""
    if frame_width % 8 != 0 or frame_height % 8 != 0:
        raise ValueError("sprite size must be a multiple of 8 in both dimensions, got {}x{}".format(frame_width, frame_height))
    attr_cols, attr_rows = frame_width // 8, frame_height // 8
    return {
        "frame_width": frame_width,
        "frame_height": frame_height,
        "frames": [_blank_legacy_frame(frame_width, frame_height, attr_cols, attr_rows) for _ in range(frame_count)],
    }


def _blank_legacy_frame(frame_width: int, frame_height: int, attr_cols: int, attr_rows: int) -> dict:
    return {
        "pixels": ["." * frame_width for _ in range(frame_height)],
        "attrs": [{"ink": DEFAULT_INK, "paper": DEFAULT_PAPER, "bright": False} for _ in range(attr_cols * attr_rows)],
    }


def _document_from_legacy_json(data: dict) -> SpriteDocument:
    frame_width, frame_height = data["frame_width"], data["frame_height"]
    document = SpriteDocument(width=frame_width, height=frame_height, frames=[], has_attrs=True)
    attr_count = document.attr_plane_bytes

    for frame_index, frame in enumerate(data["frames"]):
        rows = frame["pixels"]
        if len(rows) != frame_height:
            raise ValueError("frame {}: expected {} pixel rows, got {}".format(frame_index, frame_height, len(rows)))
        pixels = []
        for row_index, row in enumerate(rows):
            if len(row) != frame_width:
                raise ValueError("frame {} row {}: expected {} chars, got {}".format(frame_index, row_index, frame_width, len(row)))
            pixels.append(bytearray(0 if char == "." else 1 for char in row))

        cells = frame["attrs"]
        if len(cells) != attr_count:
            raise ValueError("frame {}: expected {} attribute cells, got {}".format(frame_index, attr_count, len(cells)))
        attrs = [attr_byte(cell["ink"], cell["paper"], cell["bright"]) for cell in cells]
        document.frames.append(SpriteFrame(pixels=pixels, attrs=attrs))
    return document


def parse_native_sprite(data: dict) -> FrameSequence:
    """The legacy JSON dict -> a :class:`FrameSequence`, ready for placement/build/preview."""
    return _document_from_legacy_json(data).to_frame_sequence()


def to_legacy_json(document: SpriteDocument) -> dict:
    """A document back into the legacy JSON shape.

    Only the editor uses this, and only to save a file that was *already* ``.zxspr.json``:
    a project authored before the binary formats stays editable without zxide quietly
    rewriting, renaming, or deleting files the user never asked it to touch.
    """
    return {
        "frame_width": document.width,
        "frame_height": document.height,
        "frames": [
            {
                "pixels": ["".join("#" if pixel else "." for pixel in row) for row in frame.pixels],
                "attrs": [
                    dict(zip(("ink", "paper", "bright"), attr_parts(byte)))
                    for byte in (frame.attrs or [DEFAULT_ATTR] * document.attr_cols * document.attr_rows)
                ],
            }
            for frame in document.frames
        ],
    }
