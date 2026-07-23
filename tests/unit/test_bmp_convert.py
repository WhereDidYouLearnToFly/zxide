"""Tests for BMP -> Spectrum format conversion (zxemu_core.assets.bmp_convert)."""

from __future__ import annotations

import pytest

from tests.unit.bmp_fixtures import write_bmp24
from zxemu_core.assets.bmp import read_bmp
from zxemu_core.assets.bmp_convert import (
    convert_bitmap,
    convert_font,
    convert_sprite_sequence,
    convert_sprite_sheet,
)
from zxemu_core.assets.palette import SCREEN_HEIGHT, SCREEN_WIDTH, NORMAL_RGB, attribute_offset, bitmap_offset

# --------------------------------------------------------------------------------
# convert_bitmap
# --------------------------------------------------------------------------------


def test_convert_bitmap_requires_exact_screen_size():
    image = read_bmp(write_bmp24(10, 10, lambda x, y: (0, 0, 0)))
    with pytest.raises(ValueError, match="256x192"):
        convert_bitmap(image)


def test_convert_bitmap_two_color_cell_has_no_clash_warning():
    def get_pixel(x, y):
        return (255, 255, 255) if (x < 8 and y < 8) else (0, 0, 0)

    image = read_bmp(write_bmp24(SCREEN_WIDTH, SCREEN_HEIGHT, get_pixel))
    data, warnings = convert_bitmap(image)
    assert len(data) == 6144 + 768
    assert warnings == []

    # cell (0,0) is solid white -> ink == paper == bright white (index 7), all-ink bitmap byte.
    attr = data[6144 + attribute_offset(0, 0)]
    assert attr == (1 << 6) | (7 << 3) | 7
    assert data[bitmap_offset(0, 0)] == 0xFF


def test_convert_bitmap_warns_on_three_color_cell():
    def get_pixel(x, y):
        if 8 <= x < 16 and y < 8:
            return [(255, 0, 0), (0, 255, 0), (0, 0, 255)][(x + y) % 3]
        return (0, 0, 0)

    image = read_bmp(write_bmp24(SCREEN_WIDTH, SCREEN_HEIGHT, get_pixel))
    _data, warnings = convert_bitmap(image)
    assert len(warnings) == 1
    assert warnings[0].cell_x == 1
    assert warnings[0].cell_y == 0
    assert warnings[0].color_count == 3
    assert "3 colours" in str(warnings[0])


# --------------------------------------------------------------------------------
# convert_sprite_sheet
# --------------------------------------------------------------------------------


def _checker_pixel(x, y):
    # Dark squares are "ink" (luma < 128); light squares are "paper".
    return (0, 0, 0) if (x // 4 + y // 4) % 2 == 0 else (255, 255, 255)


def test_convert_sprite_sheet_grid_layout():
    image = read_bmp(write_bmp24(16, 8, _checker_pixel))  # two 8x8 frames side by side
    seq = convert_sprite_sheet(image, 8, 8, {"grid": {"cols": 2, "rows": 1}})
    assert seq.frame_count == 2
    assert seq.frame_width == 8 and seq.frame_height == 8
    assert not seq.has_mask
    assert seq.frame_stride == 8
    # top-left 4x4 of frame 0 is dark -> the top row's high bits are set.
    assert seq.pixel_plane(0)[0] & 0xF0 == 0xF0


def test_convert_sprite_sheet_strip_layout():
    image = read_bmp(write_bmp24(24, 8, _checker_pixel))  # three 8-wide frames in a horizontal strip
    seq = convert_sprite_sheet(image, 8, 8, {"strip": {"axis": "horizontal", "count": 3}})
    assert seq.frame_count == 3


def test_convert_sprite_sheet_rejects_frame_width_not_multiple_of_8():
    image = read_bmp(write_bmp24(10, 8, lambda x, y: (0, 0, 0)))
    with pytest.raises(ValueError, match="multiple of 8"):
        convert_sprite_sheet(image, 10, 8, {"grid": {"cols": 1, "rows": 1}})


def test_convert_sprite_sheet_rejects_frame_not_fitting_image():
    image = read_bmp(write_bmp24(8, 8, lambda x, y: (0, 0, 0)))
    with pytest.raises(ValueError, match="doesn't fit"):
        convert_sprite_sheet(image, 8, 8, {"grid": {"cols": 2, "rows": 1}})


def test_convert_sprite_sheet_mask_toggle():
    transparent = (1, 2, 3)

    def get_pixel(x, y):
        return transparent if x < 4 else (0, 0, 0)

    image = read_bmp(write_bmp24(8, 8, get_pixel))
    seq = convert_sprite_sheet(
        image, 8, 8, {"grid": {"cols": 1, "rows": 1}}, generate_mask=True, mask_color=transparent
    )
    assert seq.has_mask
    assert seq.frame_stride == 16  # pixel plane + mask plane, 8 bytes each
    mask = seq.mask_plane(0)
    # Left half (transparent color) should be masked out (bit=0); right half opaque (bit=1).
    assert mask[0] == 0x0F


def test_convert_sprite_sheet_mask_requires_color():
    image = read_bmp(write_bmp24(8, 8, lambda x, y: (0, 0, 0)))
    with pytest.raises(ValueError, match="mask_color"):
        convert_sprite_sheet(image, 8, 8, {"grid": {"cols": 1, "rows": 1}}, generate_mask=True)


# --------------------------------------------------------------------------------
# convert_sprite_sequence
# --------------------------------------------------------------------------------


def test_convert_sprite_sequence_preserves_order():
    frames = [
        read_bmp(write_bmp24(8, 8, lambda x, y: (0, 0, 0))),
        read_bmp(write_bmp24(8, 8, lambda x, y: (255, 255, 255))),
    ]
    seq = convert_sprite_sequence(frames)
    assert seq.frame_count == 2
    assert seq.pixel_plane(0) == bytes([0xFF] * 8)  # all-dark frame -> all-ink bits
    assert seq.pixel_plane(1) == bytes([0x00] * 8)  # all-white frame -> no ink bits


def test_convert_sprite_sequence_rejects_mismatched_frame_size():
    frames = [
        read_bmp(write_bmp24(8, 8, lambda x, y: (0, 0, 0))),
        read_bmp(write_bmp24(16, 8, lambda x, y: (0, 0, 0))),
    ]
    with pytest.raises(ValueError, match="expected 8x8"):
        convert_sprite_sequence(frames)


def test_convert_sprite_sequence_rejects_empty_list():
    with pytest.raises(ValueError, match="at least one"):
        convert_sprite_sequence([])


# --------------------------------------------------------------------------------
# convert_font
# --------------------------------------------------------------------------------


def test_convert_font_infers_grid_from_image_size():
    image = read_bmp(write_bmp24(16, 8, _checker_pixel))  # two 8x8 glyphs
    seq = convert_font(image)
    assert seq.frame_count == 2
    assert not seq.has_mask


def test_convert_font_rejects_non_dividing_size_without_explicit_layout():
    image = read_bmp(write_bmp24(10, 8, lambda x, y: (0, 0, 0)))
    with pytest.raises(ValueError, match="explicit layout"):
        convert_font(image)


# --------------------------------------------------------------------------------
# convert_sprite_sheet / convert_sprite_sequence -- generate_attrs
# --------------------------------------------------------------------------------

_RED = NORMAL_RGB[2]
_CYAN = NORMAL_RGB[5]
_GREEN = NORMAL_RGB[4]
_YELLOW = NORMAL_RGB[6]


def test_convert_sprite_sheet_attrs_single_cell():
    # Deliberately unequal pixel counts (1 row vs 7 rows) so "most frequent = paper"
    # is unambiguous -- an even split would depend on unspecified tie-breaking.
    def get_pixel(x, y):
        return _RED if y < 1 else _CYAN  # 8 red pixels (ink), 56 cyan pixels (paper)

    image = read_bmp(write_bmp24(8, 8, get_pixel))
    seq = convert_sprite_sheet(image, 8, 8, {"grid": {"cols": 1, "rows": 1}}, generate_attrs=True)
    assert seq.has_attrs
    assert seq.frame_stride == 8 + 1  # 8 pixel bytes + 1 attr byte (one 8x8 cell)
    attr = seq.attr_plane(0)[0]
    assert attr & 0x40 == 0  # not bright
    assert attr & 0x07 == 2  # ink = red
    assert (attr >> 3) & 0x07 == 5  # paper = cyan
    # row 0 (red) is ink, row 1 (cyan) is paper
    pixels = seq.pixel_plane(0)
    assert pixels[0] == 0xFF
    assert pixels[1] == 0x00


def test_convert_sprite_sheet_attrs_two_cells_independent_colors():
    def get_pixel(x, y):
        return _GREEN if x < 8 else _YELLOW  # left 8x8 cell green, right cell yellow

    image = read_bmp(write_bmp24(16, 8, get_pixel))
    seq = convert_sprite_sheet(image, 8, 8, {"grid": {"cols": 2, "rows": 1}}, generate_attrs=True)
    assert seq.frame_count == 2
    left_attr = seq.attr_plane(0)[0]
    right_attr = seq.attr_plane(1)[0]
    assert left_attr & 0x07 == 4  # green ink (solid colour -> ink==paper==that colour)
    assert right_attr & 0x07 == 6  # yellow ink


def test_convert_sprite_sheet_attrs_requires_frame_height_multiple_of_8():
    image = read_bmp(write_bmp24(8, 10, lambda x, y: (0, 0, 0)))
    with pytest.raises(ValueError, match="frame_height"):
        convert_sprite_sheet(image, 8, 10, {"grid": {"cols": 1, "rows": 1}}, generate_attrs=True)


def test_convert_sprite_sheet_attrs_reports_clash_warnings():
    def get_pixel(x, y):
        return [_RED, _GREEN, _CYAN][(x + y) % 3]

    image = read_bmp(write_bmp24(8, 8, get_pixel))
    warnings = []
    convert_sprite_sheet(image, 8, 8, {"grid": {"cols": 1, "rows": 1}}, generate_attrs=True, warnings=warnings)
    assert len(warnings) == 1
    assert warnings[0].color_count == 3


def test_convert_sprite_sheet_attrs_combined_with_mask():
    transparent = (1, 2, 3)

    def get_pixel(x, y):
        return transparent if x < 4 else _RED

    image = read_bmp(write_bmp24(8, 8, get_pixel))
    seq = convert_sprite_sheet(
        image, 8, 8, {"grid": {"cols": 1, "rows": 1}},
        generate_mask=True, mask_color=transparent, generate_attrs=True,
    )
    assert seq.has_mask and seq.has_attrs
    assert seq.frame_stride == 8 + 8 + 1  # pixel + mask + attrs
    assert seq.mask_plane(0)[0] == 0x0F  # right half opaque


def test_convert_sprite_sequence_attrs_each_frame_independent():
    frame0 = read_bmp(write_bmp24(8, 8, lambda x, y: _RED))
    frame1 = read_bmp(write_bmp24(8, 8, lambda x, y: _CYAN))
    seq = convert_sprite_sequence([frame0, frame1], generate_attrs=True)
    assert seq.has_attrs
    assert seq.attr_plane(0)[0] & 0x07 == 2  # red
    assert seq.attr_plane(1)[0] & 0x07 == 5  # cyan
