"""Tests for the level-layout converter (zxemu_core.assets.tilemap_convert)."""

from __future__ import annotations

import pytest

from zxemu_core.assets.tilemap_convert import TilemapData, pack_tilemap, parse_tilemap_json


def test_parse_tilemap_json_reads_shape():
    tilemap = parse_tilemap_json(
        {"tileset": "tileset_forest", "width": 3, "height": 2, "tiles": [[0, 1, 2], [1, 1, 0]]}
    )
    assert tilemap.tileset_symbol == "tileset_forest"
    assert tilemap.width == 3 and tilemap.height == 2
    assert tilemap.tiles == [[0, 1, 2], [1, 1, 0]]


def test_parse_tilemap_json_rejects_height_mismatch():
    with pytest.raises(ValueError, match="height"):
        parse_tilemap_json({"tileset": "t", "width": 2, "height": 3, "tiles": [[0, 0], [0, 0]]})


def test_parse_tilemap_json_rejects_row_width_mismatch():
    with pytest.raises(ValueError, match="row 1"):
        parse_tilemap_json({"tileset": "t", "width": 2, "height": 2, "tiles": [[0, 0], [0, 0, 0]]})


def test_pack_tilemap_one_byte_per_tile():
    tilemap = TilemapData(tileset_symbol="t", width=3, height=2, tiles=[[0, 1, 2], [3, 4, 5]])
    packed = pack_tilemap(tilemap, tileset_frame_count=6)
    assert packed == bytes([0, 1, 2, 3, 4, 5])


def test_pack_tilemap_nibble_packing_halves_size():
    tilemap = TilemapData(tileset_symbol="t", width=4, height=1, tiles=[[1, 2, 3, 4]])
    packed = pack_tilemap(tilemap, tileset_frame_count=16, pack_nibble=True)
    assert packed == bytes([1 | (2 << 4), 3 | (4 << 4)])


def test_pack_tilemap_nibble_packing_pads_odd_row_width():
    tilemap = TilemapData(tileset_symbol="t", width=3, height=1, tiles=[[5, 6, 7]])
    packed = pack_tilemap(tilemap, tileset_frame_count=16, pack_nibble=True)
    assert packed == bytes([5 | (6 << 4), 7])  # last nibble of the row pads with 0


def test_pack_tilemap_rejects_nibble_packing_over_16_tiles():
    tilemap = TilemapData(tileset_symbol="t", width=1, height=1, tiles=[[0]])
    with pytest.raises(ValueError, match="16 or fewer"):
        pack_tilemap(tilemap, tileset_frame_count=17, pack_nibble=True)


def test_pack_tilemap_rejects_out_of_range_tile_index():
    tilemap = TilemapData(tileset_symbol="t", width=1, height=1, tiles=[[5]])
    with pytest.raises(ValueError, match="out of range"):
        pack_tilemap(tilemap, tileset_frame_count=5)
