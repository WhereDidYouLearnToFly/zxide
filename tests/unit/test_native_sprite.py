"""Tests for the native .zxspr.json sprite format (zxemu_core.assets.native_sprite)."""

from __future__ import annotations

import pytest

from zxemu_core.assets.native_sprite import blank_sprite_data, parse_native_sprite


def test_blank_sprite_data_shape():
    data = blank_sprite_data(8, 8, frame_count=2)
    assert data["frame_width"] == 8 and data["frame_height"] == 8
    assert len(data["frames"]) == 2
    frame = data["frames"][0]
    assert len(frame["pixels"]) == 8
    assert all(row == "." * 8 for row in frame["pixels"])
    assert frame["attrs"] == [{"ink": 0, "paper": 7, "bright": False}]


def test_blank_sprite_data_rejects_non_multiple_of_8():
    with pytest.raises(ValueError, match="multiple of 8"):
        blank_sprite_data(10, 8)


def test_blank_frames_are_independent_copies():
    data = blank_sprite_data(8, 8, frame_count=2)
    data["frames"][0]["pixels"][0] = "########"
    assert data["frames"][1]["pixels"][0] == "........"


def test_parse_native_sprite_pixels_and_attrs():
    data = {
        "frame_width": 8,
        "frame_height": 8,
        "frames": [
            {
                "pixels": ["########", "........", "........", "........",
                           "........", "........", "........", "........"],
                "attrs": [{"ink": 2, "paper": 5, "bright": False}],
            }
        ],
    }
    seq = parse_native_sprite(data)
    assert seq.frame_count == 1
    assert seq.has_attrs and not seq.has_mask
    assert seq.pixel_plane(0)[0] == 0xFF
    assert seq.pixel_plane(0)[1] == 0x00
    attr = seq.attr_plane(0)[0]
    assert attr & 0x07 == 2
    assert (attr >> 3) & 0x07 == 5
    assert attr & 0x40 == 0


def test_parse_native_sprite_bright_flag():
    data = blank_sprite_data(8, 8)
    data["frames"][0]["attrs"][0] = {"ink": 1, "paper": 0, "bright": True}
    seq = parse_native_sprite(data)
    assert seq.attr_plane(0)[0] & 0x40 == 0x40


def test_parse_native_sprite_multi_cell():
    data = blank_sprite_data(16, 16)  # 2x2 attr cells
    assert len(data["frames"][0]["attrs"]) == 4
    data["frames"][0]["attrs"][3] = {"ink": 4, "paper": 6, "bright": False}
    seq = parse_native_sprite(data)
    assert seq.attr_cols == 2 and seq.attr_rows == 2
    assert seq.attr_plane(0)[3] & 0x07 == 4


def test_parse_native_sprite_rejects_wrong_row_count():
    data = blank_sprite_data(8, 8)
    data["frames"][0]["pixels"].pop()
    with pytest.raises(ValueError, match="pixel rows"):
        parse_native_sprite(data)


def test_parse_native_sprite_rejects_wrong_row_width():
    data = blank_sprite_data(8, 8)
    data["frames"][0]["pixels"][0] = "....."
    with pytest.raises(ValueError, match="chars"):
        parse_native_sprite(data)


def test_parse_native_sprite_rejects_wrong_attr_count():
    data = blank_sprite_data(8, 8)
    data["frames"][0]["attrs"].append({"ink": 0, "paper": 0, "bright": False})
    with pytest.raises(ValueError, match="attribute cells"):
        parse_native_sprite(data)


def test_parse_native_sprite_rejects_out_of_range_color():
    data = blank_sprite_data(8, 8)
    data["frames"][0]["attrs"][0] = {"ink": 9, "paper": 0, "bright": False}
    with pytest.raises(ValueError, match="0-7"):
        parse_native_sprite(data)


def test_round_trip_through_json():
    import json

    data = blank_sprite_data(8, 8)
    data["frames"][0]["pixels"][2] = "..####.."
    reloaded = json.loads(json.dumps(data))
    seq = parse_native_sprite(reloaded)
    assert seq.pixel_plane(0)[2] == 0x3C
