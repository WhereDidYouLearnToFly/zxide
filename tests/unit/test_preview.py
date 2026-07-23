"""Tests for standalone asset preview rendering (zxemu_core.assets.preview)."""

from __future__ import annotations

from zxemu_core.assets.manifest import FrameSequence
from zxemu_core.assets.palette import BRIGHT_RGB, NORMAL_RGB
from zxemu_core.assets.preview import (
    render_frame_rgb,
    render_frame_with_attrs_rgb,
    render_sequence_frame_rgb,
    render_sheet_rgb,
    render_tilemap_rgb,
)
from zxemu_core.assets.tilemap_convert import TilemapData


def test_render_frame_rgb_maps_ink_and_paper():
    # A single 8x8 frame, top row all-ink (0xFF), rest all-paper (0x00).
    frame = bytes([0xFF] + [0x00] * 7)
    attr = 0x07  # white ink, black paper, normal brightness
    buffer = render_frame_rgb(frame, 8, 8, attr)
    ink_rgb = bytes(NORMAL_RGB[7])
    paper_rgb = bytes(NORMAL_RGB[0])
    assert buffer[0:3] == ink_rgb  # top-left pixel is ink
    assert buffer[8 * 3 : 8 * 3 + 3] == paper_rgb  # first pixel of row 1 is paper


def test_render_frame_rgb_bright_attribute():
    frame = bytes([0xFF] * 8)
    buffer = render_frame_rgb(frame, 8, 8, attr_byte=0x40 | 7)  # bright white ink
    assert buffer[0:3] == bytes(BRIGHT_RGB[7])


def test_render_sheet_rgb_tiles_frames_into_a_grid():
    # Two 8x8 frames: frame 0 all-ink, frame 1 all-paper.
    data = bytes([0xFF] * 8) + bytes([0x00] * 8)
    seq = FrameSequence(frame_width=8, frame_height=8, frame_count=2, has_mask=False, data=data)
    buffer, width, height = render_sheet_rgb(seq, cols=2)
    assert (width, height) == (16, 8)
    ink_rgb = bytes(NORMAL_RGB[7])
    paper_rgb = bytes(NORMAL_RGB[0])
    assert buffer[0:3] == ink_rgb  # frame 0's top-left pixel
    assert buffer[8 * 3 : 8 * 3 + 3] == paper_rgb  # frame 1's top-left pixel, at x offset 8


def test_render_tilemap_rgb_composites_tileset_frames():
    tileset_data = bytes([0xFF] * 8) + bytes([0x00] * 8)  # tile 0 = ink, tile 1 = paper
    tileset = FrameSequence(frame_width=8, frame_height=8, frame_count=2, has_mask=False, data=tileset_data)
    tilemap = TilemapData(tileset_symbol="t", width=2, height=1, tiles=[[1, 0]])  # paper tile, then ink tile
    buffer, width, height = render_tilemap_rgb(tilemap, tileset)
    assert (width, height) == (16, 8)
    ink_rgb = bytes(NORMAL_RGB[7])
    paper_rgb = bytes(NORMAL_RGB[0])
    assert buffer[0:3] == paper_rgb  # left cell is tile 1 (paper)
    assert buffer[8 * 3 : 8 * 3 + 3] == ink_rgb  # right cell is tile 0 (ink)


def test_render_frame_with_attrs_rgb_uses_per_cell_colour():
    # 16x8, two cells: left all-ink with attr (ink=2/red), right all-ink with attr (ink=4/green).
    pixel_plane = bytes([0xFF, 0xFF] * 8)  # both byte-columns all-ink, every row
    attr_plane = bytes([2, 4])  # left cell red ink, right cell green ink (paper=0 for both)
    buffer = render_frame_with_attrs_rgb(pixel_plane, attr_plane, 16, 8)
    assert buffer[0:3] == bytes(NORMAL_RGB[2])  # left cell red
    assert buffer[8 * 3 : 8 * 3 + 3] == bytes(NORMAL_RGB[4])  # right cell green


def test_render_sequence_frame_rgb_dispatches_on_has_attrs():
    plain = FrameSequence(frame_width=8, frame_height=8, frame_count=1, has_mask=False, data=bytes([0xFF] * 8))
    plain_rgb = render_sequence_frame_rgb(plain, 0, attr_byte=0x07)
    assert plain_rgb[0:3] == bytes(NORMAL_RGB[7])

    attrs_data = bytes([0xFF] * 8) + bytes([2])  # pixel plane + 1 attr byte (ink=2, paper=0)
    attributed = FrameSequence(
        frame_width=8, frame_height=8, frame_count=1, has_mask=False, has_attrs=True, data=attrs_data
    )
    attributed_rgb = render_sequence_frame_rgb(attributed, 0)
    assert attributed_rgb[0:3] == bytes(NORMAL_RGB[2])


def test_render_sheet_rgb_uses_per_frame_attrs_when_present():
    # frame 0: ink=2 (red); frame 1: ink=4 (green) -- each an all-ink 8x8 cell.
    data = (bytes([0xFF] * 8) + bytes([2])) + (bytes([0xFF] * 8) + bytes([4]))
    seq = FrameSequence(frame_width=8, frame_height=8, frame_count=2, has_mask=False, has_attrs=True, data=data)
    buffer, width, height = render_sheet_rgb(seq, cols=2)
    assert buffer[0:3] == bytes(NORMAL_RGB[2])
    assert buffer[8 * 3 : 8 * 3 + 3] == bytes(NORMAL_RGB[4])
