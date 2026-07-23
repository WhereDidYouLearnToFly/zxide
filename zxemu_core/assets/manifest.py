"""The data shapes an asset is described by, independent of any converter or UI.

Two things live here:

``AssetEntry`` is what a project's manifest records about one imported asset --
where its source lives, what kind of thing it is, what label the build should give it,
and where in memory it belongs (or ``"auto"``, meaning "you decide"). It is pure data:
serialisable, and the same shape whether it arrived via drag-drop, a menu command, or a
hand-edited ``zxide.json``.

``FrameSequence`` is the shape three different asset kinds converge on --
``sprite_sheet``, ``sprite_sequence``, and ``font`` all produce one, regardless of
whether their source was a single sliced sheet, a stack of individual same-sized
images, or a character-set bitmap. Everything downstream (the Inspector's preview, the
build's ``incbin`` + ``equ`` emission, and eventually a logic graph's "draw sprite"
action) reads a ``FrameSequence`` and never needs to know which import path produced
it. Collapsing three input shapes onto one output shape is the point: it means "add a
new way to author frames" is a converter-only change, never a change to anything that
consumes frames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AssetKind(str, Enum):
    BITMAP = "bitmap"
    SPRITE_SHEET = "sprite_sheet"
    SPRITE_SEQUENCE = "sprite_sequence"
    FONT = "font"
    TILEMAP = "tilemap"
    BINARY = "binary"
    PT3 = "pt3"
    BEEPER_SFX = "beeper_sfx"


# Kinds whose converter output is a FrameSequence (see below) -- they share every
# downstream code path (preview, equ emission) rather than each inventing its own.
FRAME_SEQUENCE_KINDS = frozenset({AssetKind.SPRITE_SHEET, AssetKind.SPRITE_SEQUENCE, AssetKind.FONT})


@dataclass
class AssetEntry:
    """One imported asset, as recorded in the project manifest.

    ``source`` is a single project-relative path for every kind except
    ``sprite_sequence``, where it is an ordered list of paths -- one whole image per
    frame, rather than one sheet to slice. ``placement`` is either the literal string
    ``"auto"`` (let the build's free-space search choose a home) or a resolved
    ``{"bank": <id>, "offset": <int>}``. ``params`` carries whatever the asset's kind
    needs beyond that -- frame size/layout for sprites, ``first_char_code`` for fonts,
    ``tileset_symbol``/dimensions for tilemaps -- so this dataclass doesn't grow a new
    field for every kind that gets added.
    """

    id: str
    source: str | list[str]
    kind: AssetKind
    symbol: str
    placement: str | dict[str, Any] = "auto"
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "kind": self.kind.value,
            "symbol": self.symbol,
            "placement": self.placement,
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AssetEntry":
        return cls(
            id=data["id"],
            source=data["source"],
            kind=AssetKind(data["kind"]),
            symbol=data["symbol"],
            placement=data.get("placement", "auto"),
            params=dict(data.get("params", {})),
        )


@dataclass
class FrameSequence:
    """A run of equal-sized frames, the shape ``sprite_sheet``/``sprite_sequence``/``font`` all produce.

    ``data`` holds every frame back to back, each ``frame_stride`` bytes, in a fixed
    plane order: the packed 1bpp pixel plane (``bytes_per_row * frame_height`` bytes,
    row-major, MSB-first, no screen interleaving -- that scrambling is a hardware
    *live-screen* property, not how standalone sprite/font data sits in RAM), then a
    same-sized mask plane when ``has_mask`` is set, then an attribute plane when
    ``has_attrs`` is set -- one real Spectrum attribute byte (ink/paper/bright) per 8x8
    cell, row-major, letting a sprite carry actual per-cell colour rather than being
    plotted in a single colour chosen at draw time. ``has_attrs`` requires
    ``frame_height`` to also be a multiple of 8 (not just ``frame_width``), since an
    attribute cell is 8x8.
    """

    frame_width: int
    frame_height: int
    frame_count: int
    has_mask: bool
    data: bytes
    has_attrs: bool = False

    def __post_init__(self) -> None:
        if self.frame_width % 8 != 0:
            raise ValueError(f"frame_width must be a multiple of 8, got {self.frame_width}")
        if self.has_attrs and self.frame_height % 8 != 0:
            raise ValueError(f"frame_height must be a multiple of 8 for attributes, got {self.frame_height}")
        expected = self.frame_count * self.frame_stride
        if len(self.data) != expected:
            raise ValueError(f"FrameSequence data is {len(self.data)} bytes, expected {expected}")

    @property
    def bytes_per_row(self) -> int:
        return self.frame_width // 8

    @property
    def plane_bytes(self) -> int:
        return self.bytes_per_row * self.frame_height

    @property
    def attr_cols(self) -> int:
        return self.frame_width // 8

    @property
    def attr_rows(self) -> int:
        return self.frame_height // 8

    @property
    def attr_plane_bytes(self) -> int:
        return self.attr_cols * self.attr_rows

    @property
    def frame_stride(self) -> int:
        stride = self.plane_bytes
        if self.has_mask:
            stride += self.plane_bytes
        if self.has_attrs:
            stride += self.attr_plane_bytes
        return stride

    def frame(self, index: int) -> bytes:
        """The raw bytes of frame ``index`` (pixel plane, then mask, then attributes -- whichever are present)."""
        if not 0 <= index < self.frame_count:
            raise IndexError(f"frame {index} out of range (0..{self.frame_count - 1})")
        start = index * self.frame_stride
        return self.data[start : start + self.frame_stride]

    def pixel_plane(self, index: int) -> bytes:
        return self.frame(index)[: self.plane_bytes]

    def mask_plane(self, index: int) -> bytes | None:
        if not self.has_mask:
            return None
        frame = self.frame(index)
        return frame[self.plane_bytes : self.plane_bytes * 2]

    def attr_plane(self, index: int) -> bytes | None:
        if not self.has_attrs:
            return None
        frame = self.frame(index)
        start = self.plane_bytes * (2 if self.has_mask else 1)
        return frame[start : start + self.attr_plane_bytes]
