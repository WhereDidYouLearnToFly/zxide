"""Suffix -> kind guessing, and ``convert_asset``: the one entry point every caller uses.

Both the import UI (deciding what dialog to show after a drag-drop) and the build-time
regenerator (turning a manifest into bytes) need "given this asset, which converter do
I call, with what". Centralising that dispatch here means neither has to duplicate the
kind-to-converter mapping, and a new asset kind is a one-place change.

``convert_asset`` takes plain callables for anything filesystem- or manifest-shaped
(``read_bytes``, ``tileset_frame_count``) rather than a ``Project`` or a ``Path``
directly, so this module -- like the rest of ``zxemu_core`` -- has no dependency on
``zxemu_ui.workspace`` and stays testable with in-memory fixtures.
"""

from __future__ import annotations

import json
from typing import Callable

from zxemu_core.assets import beeper_sfx, binary_convert, bmp_convert, native_sprite, pt3_convert, tilemap_convert
from zxemu_core.assets.bmp import read_bmp
from zxemu_core.assets.manifest import AssetEntry, AssetKind, FrameSequence

# Sniffed from a dropped file's name to pick a sensible default kind for the import
# dialog -- the user can always override it (e.g. a .bmp defaults to `bitmap` but may
# really be a `sprite_sheet` or `font`).
SUFFIX_KIND_HINTS: dict[str, AssetKind] = {
    ".bmp": AssetKind.BITMAP,
    ".bin": AssetKind.BINARY,
    ".pt3": AssetKind.PT3,
    beeper_sfx.SUFFIX: AssetKind.BEEPER_SFX,
}


def guess_kind(filename: str) -> AssetKind | None:
    lowered = filename.lower()
    if lowered.endswith(".map.json"):
        return AssetKind.TILEMAP
    if lowered.endswith(native_sprite.NATIVE_SUFFIX):
        return AssetKind.SPRITE_SHEET
    for suffix, kind in SUFFIX_KIND_HINTS.items():
        if lowered.endswith(suffix):
            return kind
    return None


ConvertResult = bytes | FrameSequence


def convert_asset(
    entry: AssetEntry,
    *,
    read_bytes: Callable[[str], bytes],
    tileset_frame_count: Callable[[str], int] | None = None,
    warnings: list[str] | None = None,
) -> ConvertResult:
    """Run the converter for ``entry``.

    ``read_bytes(path)`` loads one source file's raw bytes (project-relative path in,
    bytes out) -- the only filesystem access any converter needs, and the seam that
    lets tests substitute in-memory fixtures. ``tileset_frame_count(symbol)`` resolves
    another asset's frame count, needed only for ``tilemap`` entries. ``warnings``, if
    given, collects non-fatal issues (currently only ``bitmap``'s colour-clash cells).
    """
    kind = entry.kind
    params = entry.params

    if kind is AssetKind.BITMAP:
        image = read_bmp(read_bytes(entry.source))
        data, clashes = bmp_convert.convert_bitmap(image)
        if warnings is not None:
            warnings.extend(str(c) for c in clashes)
        return data

    if kind is AssetKind.SPRITE_SHEET:
        if isinstance(entry.source, str) and entry.source.lower().endswith(native_sprite.NATIVE_SUFFIX):
            # A sprite drawn in zxide's own pixel editor -- already plain pixels/attrs,
            # no image decoding or layout params involved.
            return native_sprite.parse_native_sprite(json.loads(read_bytes(entry.source).decode("utf-8")))
        image = read_bmp(read_bytes(entry.source))
        sprite_warnings: list = []
        result = bmp_convert.convert_sprite_sheet(
            image,
            params["frame_width"],
            params["frame_height"],
            params["layout"],
            generate_mask=params.get("generate_mask", False),
            mask_color=_mask_color(params),
            generate_attrs=params.get("generate_attrs", False),
            warnings=sprite_warnings,
        )
        if warnings is not None:
            warnings.extend(str(w) for w in sprite_warnings)
        return result

    if kind is AssetKind.SPRITE_SEQUENCE:
        images = [read_bmp(read_bytes(path)) for path in entry.source]
        sprite_warnings = []
        result = bmp_convert.convert_sprite_sequence(
            images,
            generate_mask=params.get("generate_mask", False),
            mask_color=_mask_color(params),
            generate_attrs=params.get("generate_attrs", False),
            warnings=sprite_warnings,
        )
        if warnings is not None:
            warnings.extend(str(w) for w in sprite_warnings)
        return result

    if kind is AssetKind.FONT:
        frame_width, frame_height = params.get("frame_width", 8), params.get("frame_height", 8)
        if isinstance(entry.source, str) and entry.source.lower().endswith(".bmp"):
            image = read_bmp(read_bytes(entry.source))
            return bmp_convert.convert_font(image, frame_width, frame_height, params.get("layout"))
        raw = binary_convert.convert_binary(read_bytes(entry.source))
        stride = (frame_width // 8) * frame_height
        if len(raw) % stride != 0:
            raise ValueError(f"font binary is {len(raw)} bytes, not a multiple of the {stride}-byte glyph stride")
        return FrameSequence(frame_width, frame_height, len(raw) // stride, False, raw)

    if kind is AssetKind.BINARY:
        return binary_convert.convert_binary(read_bytes(entry.source), params.get("expected_length"))

    if kind is AssetKind.PT3:
        return pt3_convert.convert_pt3(read_bytes(entry.source))

    if kind is AssetKind.BEEPER_SFX:
        return beeper_sfx.convert_beeper_sfx(read_bytes(entry.source).decode("utf-8"))

    if kind is AssetKind.TILEMAP:
        tilemap = tilemap_convert.parse_tilemap_json(json.loads(read_bytes(entry.source).decode("utf-8")))
        if tileset_frame_count is None:
            raise ValueError("tilemap conversion needs a tileset_frame_count resolver")
        count = tileset_frame_count(tilemap.tileset_symbol)
        return tilemap_convert.pack_tilemap(tilemap, count, pack_nibble=params.get("pack_nibble", False))

    raise ValueError(f"no converter registered for asset kind {kind!r}")


def _mask_color(params: dict) -> tuple[int, int, int] | None:
    color = params.get("mask_color")
    return tuple(color) if color else None
