"""Tests for asset-kind dispatch (zxemu_core.assets.registry)."""

from __future__ import annotations

import json

import pytest

from tests.unit.bmp_fixtures import write_bmp24
from zxemu_core.assets.manifest import AssetEntry, AssetKind, FrameSequence
from zxemu_core.assets.native_sprite import blank_sprite_data
from zxemu_core.assets.registry import convert_asset, guess_kind


def test_guess_kind_from_suffix():
    assert guess_kind("hero.bmp") == AssetKind.BITMAP
    assert guess_kind("data.bin") == AssetKind.BINARY
    assert guess_kind("song.pt3") == AssetKind.PT3
    assert guess_kind("boom.zxsfx") == AssetKind.BEEPER_SFX
    assert guess_kind("level1.map.json") == AssetKind.TILEMAP
    assert guess_kind("mystery.xyz") is None


def _sources(mapping: dict[str, bytes]):
    return lambda path: mapping[path]


def test_convert_asset_bitmap():
    screen = write_bmp24(256, 192, lambda x, y: (0, 0, 0))
    entry = AssetEntry(id="s", source="screen.bmp", kind=AssetKind.BITMAP, symbol="screen")
    result = convert_asset(entry, read_bytes=_sources({"screen.bmp": screen}))
    assert isinstance(result, bytes)
    assert len(result) == 6144 + 768


def test_convert_asset_bitmap_collects_warnings():
    def get_pixel(x, y):
        if x < 8 and y < 8:
            return [(255, 0, 0), (0, 255, 0), (0, 0, 255)][(x + y) % 3]
        return (0, 0, 0)

    screen = write_bmp24(256, 192, get_pixel)
    entry = AssetEntry(id="s", source="screen.bmp", kind=AssetKind.BITMAP, symbol="screen")
    warnings: list[str] = []
    convert_asset(entry, read_bytes=_sources({"screen.bmp": screen}), warnings=warnings)
    assert len(warnings) == 1


def test_convert_asset_sprite_sheet():
    sheet = write_bmp24(16, 8, lambda x, y: (0, 0, 0))
    entry = AssetEntry(
        id="h",
        source="hero.bmp",
        kind=AssetKind.SPRITE_SHEET,
        symbol="hero",
        params={"frame_width": 8, "frame_height": 8, "layout": {"grid": {"cols": 2, "rows": 1}}},
    )
    result = convert_asset(entry, read_bytes=_sources({"hero.bmp": sheet}))
    assert isinstance(result, FrameSequence)
    assert result.frame_count == 2


def test_convert_asset_sprite_sequence():
    frames = {
        "walk0.bmp": write_bmp24(8, 8, lambda x, y: (0, 0, 0)),
        "walk1.bmp": write_bmp24(8, 8, lambda x, y: (255, 255, 255)),
    }
    entry = AssetEntry(id="w", source=["walk0.bmp", "walk1.bmp"], kind=AssetKind.SPRITE_SEQUENCE, symbol="walk")
    result = convert_asset(entry, read_bytes=_sources(frames))
    assert isinstance(result, FrameSequence)
    assert result.frame_count == 2


def test_convert_asset_font_from_bmp():
    sheet = write_bmp24(16, 8, lambda x, y: (0, 0, 0))
    entry = AssetEntry(id="f", source="font.bmp", kind=AssetKind.FONT, symbol="font")
    result = convert_asset(entry, read_bytes=_sources({"font.bmp": sheet}))
    assert isinstance(result, FrameSequence)
    assert result.frame_count == 2
    assert not result.has_mask


def test_convert_asset_font_from_raw_binary():
    raw = bytes(range(16))  # two 8-byte glyphs
    entry = AssetEntry(id="f", source="font.chr", kind=AssetKind.FONT, symbol="font")
    result = convert_asset(entry, read_bytes=_sources({"font.chr": raw}))
    assert isinstance(result, FrameSequence)
    assert result.frame_count == 2
    assert result.data == raw


def test_convert_asset_binary():
    entry = AssetEntry(id="b", source="data.bin", kind=AssetKind.BINARY, symbol="data")
    result = convert_asset(entry, read_bytes=_sources({"data.bin": b"\x01\x02\x03"}))
    assert result == b"\x01\x02\x03"


def test_convert_asset_pt3():
    entry = AssetEntry(id="m", source="song.pt3", kind=AssetKind.PT3, symbol="song")
    data = b"PT3" + b"\x00" * 10
    result = convert_asset(entry, read_bytes=_sources({"song.pt3": data}))
    assert result == data


def test_convert_asset_beeper_sfx():
    entry = AssetEntry(id="x", source="boom.zxsfx", kind=AssetKind.BEEPER_SFX, symbol="boom")
    result = convert_asset(entry, read_bytes=_sources({"boom.zxsfx": b"100,4\n"}))
    assert result == (100).to_bytes(2, "little") + bytes([4]) + b"\xff\xff\x00"


def test_convert_asset_tilemap_resolves_tileset_frame_count():
    level = json.dumps({"tileset": "tileset_forest", "width": 2, "height": 1, "tiles": [[0, 1]]}).encode()
    entry = AssetEntry(id="lvl", source="level1.map.json", kind=AssetKind.TILEMAP, symbol="level1")
    result = convert_asset(
        entry,
        read_bytes=_sources({"level1.map.json": level}),
        tileset_frame_count=lambda symbol: 4,
    )
    assert result == bytes([0, 1])


def test_convert_asset_tilemap_requires_resolver():
    level = json.dumps({"tileset": "t", "width": 1, "height": 1, "tiles": [[0]]}).encode()
    entry = AssetEntry(id="lvl", source="level1.map.json", kind=AssetKind.TILEMAP, symbol="level1")
    with pytest.raises(ValueError, match="tileset_frame_count"):
        convert_asset(entry, read_bytes=_sources({"level1.map.json": level}))


def test_guess_kind_native_sprite():
    assert guess_kind("hero.zxspr.json") == AssetKind.SPRITE_SHEET


def test_convert_asset_native_sprite():
    data = blank_sprite_data(8, 8)
    data["frames"][0]["attrs"][0] = {"ink": 2, "paper": 5, "bright": False}
    raw = json.dumps(data).encode()
    entry = AssetEntry(id="s", source="hero.zxspr.json", kind=AssetKind.SPRITE_SHEET, symbol="hero")
    result = convert_asset(entry, read_bytes=_sources({"hero.zxspr.json": raw}))
    assert isinstance(result, FrameSequence)
    assert result.has_attrs
    assert result.attr_plane(0)[0] & 0x07 == 2


def test_convert_asset_sprite_sheet_generate_attrs_and_warnings():
    sheet = write_bmp24(8, 8, lambda x, y: (0, 0, 0) if x < 4 else (255, 255, 255))
    entry = AssetEntry(
        id="h", source="hero.bmp", kind=AssetKind.SPRITE_SHEET, symbol="hero",
        params={"frame_width": 8, "frame_height": 8, "layout": {"grid": {"cols": 1, "rows": 1}}, "generate_attrs": True},
    )
    result = convert_asset(entry, read_bytes=_sources({"hero.bmp": sheet}))
    assert result.has_attrs
