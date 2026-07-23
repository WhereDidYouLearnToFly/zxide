"""RGB rendering for standalone asset previews (the Inspector's job, kept Qt-free here).

``emulator_view.render_screen_rgb`` already renders the *live hardware screen*, but its
addressing assumes the screen's interleaved layout and reads through a ``Memory``
object -- neither applies to a sprite, font, or tilemap asset sitting outside any
emulated machine. These renderers exist so the Inspector can preview any
:class:`~zxemu_core.assets.manifest.FrameSequence` (from a ``sprite_sheet``,
``sprite_sequence``, or ``font``) or a composed ``tilemap`` without a live machine at
all -- pure functions from bytes to an RGB buffer, which the Qt layer then wraps in a
``QImage``.

A 1bpp frame carries no colour of its own -- it's ink/paper, not RGB -- so every
renderer here takes an ``attr_byte`` the same way the hardware would, and reuses
``palette.attr_colors`` to turn it into an actual colour pair.
"""

from __future__ import annotations

import math

from zxemu_core.assets.manifest import FrameSequence
from zxemu_core.assets.palette import attr_colors
from zxemu_core.assets.tilemap_convert import TilemapData

DEFAULT_ATTR = 0x07  # white ink, black paper, normal brightness


def render_frame_rgb(frame_bytes: bytes, width: int, height: int, attr_byte: int = DEFAULT_ATTR) -> bytearray:
    """One 1bpp plane (``width x height``, row-major MSB-first) -> a flat RGB buffer.

    Uses one colour pair for the whole frame -- for a real Spectrum attribute *per
    cell*, see ``render_frame_with_attrs_rgb``.
    """
    ink, paper = attr_colors(attr_byte)
    bytes_per_row = width // 8
    buffer = bytearray(width * height * 3)
    for y in range(height):
        row_start = y * bytes_per_row
        for byte_col in range(bytes_per_row):
            byte = frame_bytes[row_start + byte_col]
            for bit in range(8):
                x = byte_col * 8 + bit
                color = ink if (byte & (0x80 >> bit)) else paper
                o = (y * width + x) * 3
                buffer[o : o + 3] = bytes(color)
    return buffer


def render_frame_with_attrs_rgb(pixel_plane: bytes, attr_plane: bytes, width: int, height: int) -> bytearray:
    """Like ``render_frame_rgb``, but each 8x8 cell uses its own attribute -- real per-cell colour."""
    bytes_per_row = width // 8
    attr_cols = width // 8
    buffer = bytearray(width * height * 3)
    for y in range(height):
        row_start = y * bytes_per_row
        cell_row = y // 8
        for byte_col in range(bytes_per_row):
            ink, paper = attr_colors(attr_plane[cell_row * attr_cols + byte_col])
            byte = pixel_plane[row_start + byte_col]
            for bit in range(8):
                x = byte_col * 8 + bit
                color = ink if (byte & (0x80 >> bit)) else paper
                o = (y * width + x) * 3
                buffer[o : o + 3] = bytes(color)
    return buffer


def render_sequence_frame_rgb(sequence: FrameSequence, index: int, attr_byte: int = DEFAULT_ATTR) -> bytearray:
    """Render frame ``index``, using its own per-cell attributes if the sequence has them, else ``attr_byte``."""
    if sequence.has_attrs:
        return render_frame_with_attrs_rgb(
            sequence.pixel_plane(index), sequence.attr_plane(index), sequence.frame_width, sequence.frame_height
        )
    return render_frame_rgb(sequence.pixel_plane(index), sequence.frame_width, sequence.frame_height, attr_byte)


def render_sheet_rgb(
    sequence: FrameSequence, cols: int | None = None, attr_byte: int = DEFAULT_ATTR
) -> tuple[bytearray, int, int]:
    """Tile every frame in ``sequence`` into one grid image -- used for fonts, and available for sprites too.

    Returns ``(rgb_buffer, sheet_width, sheet_height)``.
    """
    if cols is None:
        cols = max(1, math.ceil(math.sqrt(sequence.frame_count)))
    rows = math.ceil(sequence.frame_count / cols)
    sheet_width = cols * sequence.frame_width
    sheet_height = rows * sequence.frame_height
    buffer = bytearray(sheet_width * sheet_height * 3)

    for index in range(sequence.frame_count):
        col, row = index % cols, index // cols
        frame_rgb = render_sequence_frame_rgb(sequence, index, attr_byte)
        _blit(buffer, sheet_width, frame_rgb, sequence.frame_width, sequence.frame_height, col * sequence.frame_width, row * sequence.frame_height)

    return buffer, sheet_width, sheet_height


def render_tilemap_rgb(
    tilemap: TilemapData, tileset: FrameSequence, attr_byte: int = DEFAULT_ATTR
) -> tuple[bytearray, int, int]:
    """Composite a whole level preview by stamping ``tileset`` frames into the tilemap's grid.

    Returns ``(rgb_buffer, pixel_width, pixel_height)``.
    """
    pixel_width = tilemap.width * tileset.frame_width
    pixel_height = tilemap.height * tileset.frame_height
    buffer = bytearray(pixel_width * pixel_height * 3)

    # Cache rendered frames -- most tiles repeat, so render each distinct tile once.
    rendered: dict[int, bytearray] = {}
    for row_index, row in enumerate(tilemap.tiles):
        for col_index, tile_index in enumerate(row):
            if tile_index not in rendered:
                rendered[tile_index] = render_sequence_frame_rgb(tileset, tile_index, attr_byte)
            _blit(
                buffer,
                pixel_width,
                rendered[tile_index],
                tileset.frame_width,
                tileset.frame_height,
                col_index * tileset.frame_width,
                row_index * tileset.frame_height,
            )

    return buffer, pixel_width, pixel_height


def _blit(dest: bytearray, dest_width: int, src: bytearray, src_width: int, src_height: int, ox: int, oy: int) -> None:
    for y in range(src_height):
        src_row_start = y * src_width * 3
        dest_row_start = ((oy + y) * dest_width + ox) * 3
        dest[dest_row_start : dest_row_start + src_width * 3] = src[src_row_start : src_row_start + src_width * 3]
