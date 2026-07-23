"""Turning artwork and data files into bytes a Z80 program can use.

Nothing here emulates a machine or touches Qt -- this package's whole job is the step
*before* a build: read a source file (a BMP, a raw binary, a hand-written level), and
produce the exact bytes the assembler will ``incbin``. Keeping it Qt-free means every
converter is a plain function tested with in-memory fixtures, and the drag-drop UI in
``zxemu_ui`` is thin presentation calling into it, the same relationship this project
already has between ``zxemu_core.debug`` and its panels.

    manifest.py         The data shapes: ``AssetEntry`` (one manifest record) and
                         ``FrameSequence`` (the shape three different sprite/font
                         imports all converge on -- see its docstring for why that
                         convergence is the whole point).
    bmp.py               A minimal, dependency-free BMP reader (no Pillow, no Qt).
    palette.py           The Spectrum's 15-colour hardware palette and screen-file
                         addressing, duplicated from ``emulator_view`` since core
                         can't import it.
    bmp_convert.py       BMP -> Spectrum format: full-screen bitmaps (with the
                         attribute-clash quantization a hardware screen needs),
                         sprite sheets, sprite sequences, and fonts -- optionally
                         with real per-cell colour (``generate_attrs``), reusing the
                         same quantization the full screen uses.
    native_sprite.py     The ``.zxspr.json`` format for sprites drawn in zxide's own
                         pixel editor rather than imported -- plain pixels/attributes,
                         no BMP round-trip needed for data that never had an image.
    binary_convert.py    The catch-all: raw bytes in, raw bytes out. Also the
                         building block a pre-packed raw-binary font reuses.
    pt3_convert.py       AY-music passthrough with a header sanity check (playback
                         is a separate, later feature).
    beeper_sfx.py        A tiny hand-authored tone-table format for the 1-bit beeper.
    tilemap_convert.py   A level's tile-index grid, referencing a tileset asset by
                         symbol rather than storing pixels of its own.
    registry.py          Suffix -> kind guessing, and ``convert_asset``: the one
                         dispatch point both the import UI and the build regenerator
                         call through, so a new asset kind is a one-place change.
    preview.py           Renders a ``FrameSequence`` or tilemap to a flat RGB buffer
                         for the Inspector -- no live machine or Qt involved.

Every converter reports failure loudly (a bad BMP, a tile index out of range, a
mismatched frame size) rather than guessing and producing quietly-wrong bytes --
consistent with the rest of the emulator core's stance that a tool which hides its own
uncertainty is worse than one that stops and says so.
"""

from __future__ import annotations

from zxemu_core.assets import (
    beeper_sfx,
    binary_convert,
    bmp,
    bmp_convert,
    native_sprite,
    palette,
    preview,
    pt3_convert,
    registry,
    tilemap_convert,
)
from zxemu_core.assets.manifest import AssetEntry, AssetKind, FrameSequence

__all__ = [
    "AssetEntry",
    "AssetKind",
    "FrameSequence",
    "beeper_sfx",
    "binary_convert",
    "bmp",
    "bmp_convert",
    "native_sprite",
    "palette",
    "preview",
    "pt3_convert",
    "registry",
    "tilemap_convert",
]
