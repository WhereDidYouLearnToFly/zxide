"""Tilemaps: a level's layout as small tile-index bytes, not a full pixel bitmap.

The actual space win a tilemap buys over a raw screen bitmap comes from indirection: a
32x24 grid of 8x8 tiles is 768 index bytes instead of 6144+768 bitmap+attribute bytes,
and a 16x16 tileset over the same area is only 192 bytes -- because the *pixels* live
once in the referenced tileset (an ordinary ``sprite_sheet``/``sprite_sequence`` asset
reused as a "palette"), and the level only records which tile goes where.

This is the one converter that can't work from its own source file alone: validating a
tile index means knowing how many frames the referenced tileset actually has, which
lives in another asset entirely. Rather than reach into a ``Project`` here (breaking
the Qt-free core/UI split), the caller resolves that lookup and passes in a plain
``tileset_frame_count`` -- this module only ever sees numbers, never the manifest.

v1's source format is a hand-authored JSON grid (there's no in-app level editor yet);
see ``parse_tilemap_json`` for the shape. It's deliberately simple -- tileset reference,
dimensions, a flat index grid -- so an importer for an established tool's format (Tiled's
``.tmx``/``.json`` being the obvious candidate) is a later converter, not a restructure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TilemapData:
    tileset_symbol: str
    width: int
    height: int
    tiles: list[list[int]]  # row-major, tiles[y][x], each an index into the tileset


def parse_tilemap_json(data: dict) -> TilemapData:
    tileset_symbol = data["tileset"]
    width, height = data["width"], data["height"]
    tiles = data["tiles"]
    if len(tiles) != height:
        raise ValueError(f"tilemap declares height {height} but has {len(tiles)} rows")
    for y, row in enumerate(tiles):
        if len(row) != width:
            raise ValueError(f"tilemap declares width {width} but row {y} has {len(row)} tiles")
    return TilemapData(tileset_symbol=tileset_symbol, width=width, height=height, tiles=tiles)


def pack_tilemap(tilemap: TilemapData, tileset_frame_count: int, pack_nibble: bool = False) -> bytes:
    """Pack a validated tilemap to bytes: 1 byte/tile, or 2 tiles/byte if ``pack_nibble``.

    Nibble packing only fits when the tileset has 16 or fewer frames; each row is
    packed independently (padding, if the width is odd, is a zero nibble at the row's
    end) so a row's start byte offset stays a simple ``row * bytes_per_row`` regardless
    of what the previous row contained.
    """
    if pack_nibble and tileset_frame_count > 16:
        raise ValueError(f"pack_nibble needs a tileset of 16 or fewer frames, got {tileset_frame_count}")

    for y, row in enumerate(tilemap.tiles):
        for x, index in enumerate(row):
            if not 0 <= index < tileset_frame_count:
                raise ValueError(
                    f"tile ({x},{y}) = {index} is out of range for a {tileset_frame_count}-frame tileset"
                )

    out = bytearray()
    if not pack_nibble:
        for row in tilemap.tiles:
            out.extend(row)
        return bytes(out)

    for row in tilemap.tiles:
        for i in range(0, len(row), 2):
            low = row[i]
            high = row[i + 1] if i + 1 < len(row) else 0
            out.append(low | (high << 4))
    return bytes(out)
