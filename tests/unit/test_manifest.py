"""Tests for the asset data shapes (zxemu_core.assets.manifest)."""

from __future__ import annotations

import pytest

from zxemu_core.assets.manifest import AssetEntry, AssetKind, FrameSequence


def test_asset_entry_round_trips_through_dict():
    entry = AssetEntry(
        id="hero",
        source="sprites/hero.bmp",
        kind=AssetKind.SPRITE_SHEET,
        symbol="hero_sprite",
        placement={"bank": "ram2", "offset": 0x100},
        params={"frame_width": 16, "frame_height": 16},
    )
    restored = AssetEntry.from_dict(entry.to_dict())
    assert restored == entry


def test_asset_entry_sprite_sequence_source_is_a_list():
    entry = AssetEntry(id="walk", source=["a.bmp", "b.bmp"], kind=AssetKind.SPRITE_SEQUENCE, symbol="walk")
    data = entry.to_dict()
    assert data["source"] == ["a.bmp", "b.bmp"]
    assert AssetEntry.from_dict(data).source == ["a.bmp", "b.bmp"]


def test_frame_sequence_stride_without_mask():
    seq = FrameSequence(frame_width=8, frame_height=8, frame_count=2, has_mask=False, data=bytes(16))
    assert seq.plane_bytes == 8
    assert seq.frame_stride == 8
    assert seq.frame(1) == bytes(8)


def test_frame_sequence_stride_with_mask():
    seq = FrameSequence(frame_width=16, frame_height=8, frame_count=1, has_mask=True, data=bytes(32))
    assert seq.plane_bytes == 16  # (16/8 bytes per row) * 8 rows
    assert seq.frame_stride == 32
    assert seq.mask_plane(0) == bytes(16)


def test_frame_sequence_rejects_non_multiple_of_8_width():
    with pytest.raises(ValueError, match="multiple of 8"):
        FrameSequence(frame_width=10, frame_height=8, frame_count=1, has_mask=False, data=bytes(8))


def test_frame_sequence_rejects_wrong_data_length():
    with pytest.raises(ValueError, match="expected"):
        FrameSequence(frame_width=8, frame_height=8, frame_count=2, has_mask=False, data=bytes(8))


def test_frame_sequence_frame_index_out_of_range():
    seq = FrameSequence(frame_width=8, frame_height=8, frame_count=1, has_mask=False, data=bytes(8))
    with pytest.raises(IndexError):
        seq.frame(1)


def test_frame_sequence_stride_with_attrs():
    # 16x16 frame: 2 attr cells wide, 2 tall -> 4 attr bytes, appended after the pixel plane.
    seq = FrameSequence(
        frame_width=16, frame_height=16, frame_count=1, has_mask=False, has_attrs=True, data=bytes(32 + 4)
    )
    assert seq.attr_cols == 2 and seq.attr_rows == 2
    assert seq.attr_plane_bytes == 4
    assert seq.frame_stride == 36
    assert seq.attr_plane(0) == bytes(4)
    assert seq.pixel_plane(0) == bytes(32)


def test_frame_sequence_stride_with_mask_and_attrs():
    # pixel(8) + mask(8) + attrs(1 cell = 1 byte) = 17
    seq = FrameSequence(
        frame_width=8, frame_height=8, frame_count=1, has_mask=True, has_attrs=True, data=bytes(17)
    )
    assert seq.frame_stride == 17
    assert seq.mask_plane(0) == bytes(8)
    assert seq.attr_plane(0) == bytes(1)


def test_frame_sequence_attrs_require_frame_height_multiple_of_8():
    with pytest.raises(ValueError, match="frame_height"):
        FrameSequence(frame_width=8, frame_height=10, frame_count=1, has_mask=False, has_attrs=True, data=bytes(1))


def test_frame_sequence_attr_plane_none_without_attrs():
    seq = FrameSequence(frame_width=8, frame_height=8, frame_count=1, has_mask=False, data=bytes(8))
    assert seq.attr_plane(0) is None
