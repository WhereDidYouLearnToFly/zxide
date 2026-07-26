"""Tests for the native sprite formats (zxemu_core.assets.native_sprite)."""

from __future__ import annotations

import json

import pytest

from zxemu_core.assets.native_sprite import (
    HEADER_BYTES,
    SUFFIX_8X8,
    SUFFIX_8X8_PIX,
    SUFFIX_16X16,
    SUFFIX_16X16_PIX,
    SUFFIX_SPRITE,
    SUFFIX_SPRITE_PIX,
    attr_byte,
    attr_parts,
    blank_sprite,
    blank_sprite_data,
    convert_sprite_file,
    load_sprite_file,
    parse_native_sprite,
    sprite_format,
    sprite_suffix,
    suffix_for,
    to_legacy_json,
)

# --- suffixes ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("hero.zx8x8", SUFFIX_8X8),
        ("hero.zx16x16", SUFFIX_16X16),
        ("hero.zxsprite", SUFFIX_SPRITE),
        ("hero.zx8x8pix", SUFFIX_8X8_PIX),
        ("hero.zx16x16pix", SUFFIX_16X16_PIX),
        ("hero.zxspritepix", SUFFIX_SPRITE_PIX),
        ("hero.zxspr.json", ".zxspr.json"),
        ("HERO.ZX8X8", SUFFIX_8X8),  # matched case-insensitively
        ("hero.bmp", None),
        ("hero.zx8x8.bak", None),  # only a real trailing suffix counts
    ],
)
def test_sprite_suffix(filename, expected):
    assert sprite_suffix(filename) == expected


def test_pix_suffix_is_not_confused_with_its_attributed_twin():
    assert sprite_format("hero.zx8x8pix").has_attrs is False
    assert sprite_format("hero.zx8x8").has_attrs is True
    assert sprite_format("hero.zxspritepix").has_header is True


@pytest.mark.parametrize(
    "width,height,has_attrs,expected",
    [
        (8, 8, True, SUFFIX_8X8),
        (16, 16, True, SUFFIX_16X16),
        (24, 8, True, SUFFIX_SPRITE),
        (8, 8, False, SUFFIX_8X8_PIX),
        (16, 16, False, SUFFIX_16X16_PIX),
        (32, 24, False, SUFFIX_SPRITE_PIX),
        (8, 16, True, SUFFIX_SPRITE),  # a fixed suffix means *both* dimensions match
    ],
)
def test_suffix_for(width, height, has_attrs, expected):
    assert suffix_for(width, height, has_attrs) == expected


def test_only_the_arbitrary_size_formats_carry_a_header():
    assert sprite_format("a.zx8x8").has_header is False
    assert sprite_format("a.zx16x16").has_header is False
    assert sprite_format("a.zxsprite").has_header is True


# --- attribute bytes -----------------------------------------------------------------


def test_attr_byte_round_trip():
    assert attr_parts(attr_byte(2, 5, False)) == (2, 5, False)
    assert attr_parts(attr_byte(1, 0, True)) == (1, 0, True)


def test_attr_byte_layout_matches_hardware():
    assert attr_byte(2, 5, True) == 0b01_101_010


def test_attr_byte_rejects_out_of_range():
    with pytest.raises(ValueError, match="0-7"):
        attr_byte(9, 0, False)


# --- blank documents -----------------------------------------------------------------


def test_blank_sprite_shape():
    document = blank_sprite(8, 8, frame_count=2)
    assert document.width == 8 and document.height == 8
    assert len(document.frames) == 2
    assert all(len(frame.pixels) == 8 for frame in document.frames)
    assert all(not any(row) for row in document.frames[0].pixels)
    assert document.frames[0].attrs == [attr_byte(0, 7, False)]


def test_blank_pixel_only_sprite_has_no_attributes():
    document = blank_sprite(16, 16, has_attrs=False)
    assert document.frames[0].attrs == []
    assert document.attr_plane_bytes == 0
    assert document.frame_stride == 32  # 2 bytes/row * 16 rows, no attribute plane


def test_blank_frames_are_independent_copies():
    document = blank_sprite(8, 8, frame_count=2)
    document.frames[0].pixels[0][0] = 1
    assert document.frames[1].pixels[0][0] == 0


def test_blank_sprite_rejects_non_multiple_of_8():
    with pytest.raises(ValueError, match="multiple of 8"):
        blank_sprite(10, 8)


def test_blank_sprite_rejects_a_size_too_big_for_the_header():
    with pytest.raises(ValueError, match=r"8\.\.255"):
        blank_sprite(8, 256)


# --- strides -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "width,height,has_attrs,stride",
    [
        (8, 8, True, 9),      # 8 pixel bytes + 1 attribute byte
        (8, 8, False, 8),
        (16, 16, True, 36),   # 32 pixel bytes + 4 attribute bytes
        (16, 16, False, 32),
        (24, 8, True, 27),    # 3 bytes/row * 8 rows + 3 cells
    ],
)
def test_frame_stride(width, height, has_attrs, stride):
    assert blank_sprite(width, height, has_attrs=has_attrs).frame_stride == stride


# --- encoding and decoding -----------------------------------------------------------


def test_fixed_size_file_has_no_header():
    document = blank_sprite(8, 8)
    document.frames[0].pixels[0][:] = bytearray([1] * 8)
    encoded = document.encode(with_header=False)
    assert len(encoded) == 9
    assert encoded[0] == 0xFF  # the first pixel row, packed MSB-first


def test_arbitrary_size_file_starts_with_width_and_height():
    document = blank_sprite(24, 8)
    encoded = document.encode(with_header=True)
    assert encoded[0] == 24 and encoded[1] == 8
    assert len(encoded) == HEADER_BYTES + document.frame_stride


def test_pixels_pack_msb_first():
    document = blank_sprite(8, 8)
    document.frames[0].pixels[2][2:6] = bytearray([1, 1, 1, 1])
    assert document.encode(with_header=False)[2] == 0x3C


def test_attributes_follow_the_pixel_plane():
    document = blank_sprite(8, 8)
    document.frames[0].attrs[0] = attr_byte(2, 5, False)
    encoded = document.encode(with_header=False)
    assert encoded[8] == attr_byte(2, 5, False)


def test_round_trip_fixed_size():
    document = blank_sprite(16, 16, frame_count=3)
    document.frames[1].pixels[4][5] = 1
    document.frames[1].attrs[3] = attr_byte(4, 6, True)
    reloaded = load_sprite_file("hero.zx16x16", document.encode(with_header=False))

    assert reloaded.width == 16 and reloaded.height == 16 and reloaded.has_attrs
    assert len(reloaded.frames) == 3
    assert reloaded.frames[1].pixels[4][5] == 1
    assert attr_parts(reloaded.frames[1].attrs[3]) == (4, 6, True)


def test_round_trip_arbitrary_size_reads_size_from_the_header():
    document = blank_sprite(24, 8, frame_count=2)
    document.frames[0].pixels[0][23] = 1
    reloaded = load_sprite_file("blob.zxsprite", document.encode(with_header=True))

    assert reloaded.width == 24 and reloaded.height == 8
    assert len(reloaded.frames) == 2
    assert reloaded.frames[0].pixels[0][23] == 1


def test_round_trip_pixel_only():
    document = blank_sprite(8, 8, frame_count=2, has_attrs=False)
    document.frames[0].pixels[7][7] = 1
    encoded = document.encode(with_header=False)
    assert len(encoded) == 16  # two 8-byte frames, no attribute bytes

    reloaded = load_sprite_file("hero.zx8x8pix", encoded)
    assert reloaded.has_attrs is False
    assert reloaded.frames[0].attrs == []
    assert reloaded.frames[0].pixels[7][7] == 1


def test_frame_count_follows_from_the_file_length():
    document = blank_sprite(8, 8, frame_count=5)
    assert len(load_sprite_file("hero.zx8x8", document.encode(with_header=False)).frames) == 5


def test_load_rejects_a_length_that_is_not_whole_frames():
    with pytest.raises(ValueError, match="not a whole number"):
        load_sprite_file("hero.zx8x8", bytes(10))  # 9-byte stride, so 10 is a partial frame


def test_load_rejects_an_empty_file():
    with pytest.raises(ValueError, match="no frames"):
        load_sprite_file("hero.zx8x8", b"")


def test_load_rejects_a_truncated_header():
    with pytest.raises(ValueError, match="too short"):
        load_sprite_file("blob.zxsprite", b"\x18")


def test_load_rejects_an_unknown_extension():
    with pytest.raises(ValueError, match="not a native sprite file"):
        load_sprite_file("hero.bmp", b"\x00")


# --- conversion to the build's shape --------------------------------------------------


def test_convert_sprite_file_produces_a_frame_sequence():
    document = blank_sprite(16, 16, frame_count=2)
    sequence = convert_sprite_file("hero.zx16x16", document.encode(with_header=False))

    assert sequence.frame_width == 16 and sequence.frame_height == 16
    assert sequence.frame_count == 2
    assert sequence.has_attrs and not sequence.has_mask
    assert sequence.header == b""  # a fixed-size format needs no header in the blob


def test_convert_sprite_file_keeps_the_header_out_of_the_frame_data():
    document = blank_sprite(24, 8)
    sequence = convert_sprite_file("blob.zxsprite", document.encode(with_header=True))

    assert sequence.header == bytes([24, 8])
    assert len(sequence.data) == sequence.frame_stride  # frames alone, header excluded
    assert sequence.frame_count == 1


def test_convert_pixel_only_file_has_no_attribute_plane():
    document = blank_sprite(8, 8, has_attrs=False)
    sequence = convert_sprite_file("hero.zx8x8pix", document.encode(with_header=False))

    assert sequence.has_attrs is False
    assert sequence.frame_stride == 8
    assert sequence.attr_plane(0) is None


def test_converted_pixels_survive_to_the_frame_sequence():
    document = blank_sprite(8, 8)
    document.frames[0].pixels[2][2:6] = bytearray([1, 1, 1, 1])
    sequence = convert_sprite_file("hero.zx8x8", document.encode(with_header=False))
    assert sequence.pixel_plane(0)[2] == 0x3C


# --- the legacy .zxspr.json shape ----------------------------------------------------


def test_legacy_json_still_loads():
    data = blank_sprite_data(8, 8)
    data["frames"][0]["pixels"][2] = "..####.."
    data["frames"][0]["attrs"][0] = {"ink": 2, "paper": 5, "bright": False}
    document = load_sprite_file("hero.zxspr.json", json.dumps(data).encode("utf-8"))

    assert document.width == 8 and document.has_attrs
    assert document.frames[0].pixels[2][2] == 1
    assert attr_parts(document.frames[0].attrs[0]) == (2, 5, False)


def test_legacy_json_converts_to_the_same_frame_sequence():
    data = blank_sprite_data(8, 8)
    data["frames"][0]["pixels"][0] = "########"
    sequence = parse_native_sprite(data)
    assert sequence.pixel_plane(0)[0] == 0xFF
    assert sequence.has_attrs


def test_legacy_json_round_trips_through_the_document():
    data = blank_sprite_data(16, 16, frame_count=2)
    data["frames"][1]["pixels"][3] = "#" * 16
    data["frames"][1]["attrs"][2] = {"ink": 1, "paper": 0, "bright": True}
    document = load_sprite_file("hero.zxspr.json", json.dumps(data).encode("utf-8"))
    assert to_legacy_json(document) == data


def test_legacy_json_rejects_wrong_row_count():
    data = blank_sprite_data(8, 8)
    data["frames"][0]["pixels"].pop()
    with pytest.raises(ValueError, match="pixel rows"):
        parse_native_sprite(data)


def test_legacy_json_rejects_wrong_row_width():
    data = blank_sprite_data(8, 8)
    data["frames"][0]["pixels"][0] = "....."
    with pytest.raises(ValueError, match="chars"):
        parse_native_sprite(data)


def test_legacy_json_rejects_wrong_attr_count():
    data = blank_sprite_data(8, 8)
    data["frames"][0]["attrs"].append({"ink": 0, "paper": 0, "bright": False})
    with pytest.raises(ValueError, match="attribute cells"):
        parse_native_sprite(data)


def test_legacy_json_rejects_out_of_range_color():
    data = blank_sprite_data(8, 8)
    data["frames"][0]["attrs"][0] = {"ink": 9, "paper": 0, "bright": False}
    with pytest.raises(ValueError, match="0-7"):
        parse_native_sprite(data)


def test_blank_sprite_data_rejects_non_multiple_of_8():
    with pytest.raises(ValueError, match="multiple of 8"):
        blank_sprite_data(10, 8)
