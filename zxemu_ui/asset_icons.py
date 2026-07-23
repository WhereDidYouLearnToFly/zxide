"""A colour and a short glyph per asset kind, so the eye can tell them apart at a glance.

Used everywhere an asset's kind needs a quick visual cue rather than reading its label:
placed-asset rectangles in the Design-mode memory map, and the Inspector's kind badge.
One table here means both stay in sync automatically when a new kind is added.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap

from zxemu_core.assets.manifest import AssetKind

# (colour, one-or-two-letter glyph) per kind. Colours are deliberately distinct hues,
# not shades of the same colour, so they stay distinguishable at a glance and to
# colour-blind users relying on the glyph as a fallback.
_KIND_STYLE: dict[AssetKind, tuple[str, str]] = {
    AssetKind.BITMAP: ("#3b82f6", "B"),
    AssetKind.SPRITE_SHEET: ("#22c55e", "S"),
    AssetKind.SPRITE_SEQUENCE: ("#14b8a6", "A"),
    AssetKind.FONT: ("#a855f7", "F"),
    AssetKind.TILEMAP: ("#f97316", "T"),
    AssetKind.BINARY: ("#9aa0a6", "#"),
    AssetKind.PT3: ("#ec4899", "M"),
    AssetKind.BEEPER_SFX: ("#eab308", "X"),
}


def color_for_kind(kind: AssetKind) -> QColor:
    hex_color, _glyph = _KIND_STYLE[kind]
    return QColor(hex_color)


def glyph_for_kind(kind: AssetKind) -> str:
    _hex_color, glyph = _KIND_STYLE[kind]
    return glyph


def icon_for_kind(kind: AssetKind, size: int = 16) -> QIcon:
    """A small rounded-square icon: the kind's colour, with its glyph centred in white."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color_for_kind(kind))
    margin = 1
    painter.drawRoundedRect(margin, margin, size - 2 * margin, size - 2 * margin, 3, 3)
    painter.setPen(Qt.white)
    font = painter.font()
    font.setPixelSize(max(8, size - 6))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, glyph_for_kind(kind))
    painter.end()
    return QIcon(pixmap)
