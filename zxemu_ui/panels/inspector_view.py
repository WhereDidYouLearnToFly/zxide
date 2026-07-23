"""InspectorView -- properties and a live preview of the selected asset.

Wired from two places: the project tree's selection (any file that matches an asset's
source) and the Design-mode memory map's ``asset_selected`` signal (clicking a placed
rectangle). Either path ends up calling ``show_asset``, which is the only place real
work happens -- converting the asset (via ``zxemu_core.assets.registry``) and handing
the result to ``zxemu_core.assets.preview`` for a Qt-free RGB render, which this panel
then wraps in a ``QPixmap``. A conversion failure (a corrupt source file, say) is shown
as an inline error rather than raised -- selecting something broken should never crash
the IDE around it.
"""

from __future__ import annotations

import json

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

from zxemu_core.assets import preview as asset_preview
from zxemu_core.assets.beeper_sfx import parse_beeper_sfx
from zxemu_core.assets.manifest import AssetKind, FrameSequence
from zxemu_core.assets.palette import SCREEN_HEIGHT, SCREEN_WIDTH, attr_colors, attribute_offset, bitmap_offset
from zxemu_core.assets.registry import convert_asset
from zxemu_core.assets.tilemap_convert import parse_tilemap_json
from zxemu_core.sound.beeper_preview import render_tone_sequence
from zxemu_ui.asset_icons import icon_for_kind
from zxemu_ui.audio_output import AudioOutput
from zxemu_ui.workspace.asset_build import auto_locate_one, cached_length

# Generous cap on a previewed clip's length, so a pathological SFX file can't demand
# an absurd audio buffer -- real sound effects are a few seconds at most.
_MAX_PREVIEW_SECONDS = 10

_PLACEHOLDER_TEXT = (
    "Nothing selected.\n\n"
    "Select an asset in the Project panel, or click a placed asset in the "
    "Design-mode memory map, to inspect it here."
)

# A visible pixel size floor -- most sprites/tiles are tiny (8x8), and a 1:1 render
# would be nearly invisible.
_MIN_PREVIEW_SCALE = 4


def _rgb_to_pixmap(buffer, width: int, height: int, scale: int = 1) -> QPixmap:
    image = QImage(bytes(buffer), width, height, width * 3, QImage.Format_RGB888).copy()
    pixmap = QPixmap.fromImage(image)
    if scale != 1:
        pixmap = pixmap.scaled(width * scale, height * scale, Qt.KeepAspectRatio, Qt.FastTransformation)
    return pixmap


class InspectorView(QWidget):
    """Shows details + a live preview of whatever asset is currently selected."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.entry = None

        self._icon_label = QLabel()
        self._title_label = QLabel()
        self._title_label.setStyleSheet("font-weight: bold;")
        header = QHBoxLayout()
        header.addWidget(self._icon_label)
        header.addWidget(self._title_label)
        header.addStretch(1)

        self._fields_label = QLabel()
        self._fields_label.setWordWrap(True)
        self._fields_label.setStyleSheet("color: palette(mid);")

        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setMinimumHeight(80)

        self._frame_spin = QSpinBox()
        self._frame_spin.setPrefix("frame ")
        self._frame_spin.valueChanged.connect(self._render_preview)
        self._frame_row = QHBoxLayout()
        self._frame_row.addWidget(self._frame_spin)
        self._frame_row.addStretch(1)

        self._tileset_button = QPushButton()
        self._tileset_button.setFlat(True)
        self._tileset_button.setStyleSheet("text-align: left; color: palette(link);")
        self._tileset_button.clicked.connect(self._goto_tileset)

        self._auto_locate_button = QPushButton("Auto-locate this asset")
        self._auto_locate_button.clicked.connect(self._auto_locate)

        self._play_button = QPushButton("▶ Play")
        self._play_button.clicked.connect(self._play_beeper_sfx)
        self._preview_audio: AudioOutput | None = None  # kept alive for the duration of playback

        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #e05252;")

        self._message_label = QLabel(_PLACEHOLDER_TEXT)
        self._message_label.setWordWrap(True)
        self._message_label.setAlignment(Qt.AlignTop)
        self._message_label.setStyleSheet("color: palette(mid);")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addLayout(header)
        layout.addWidget(self._fields_label)
        layout.addWidget(self._preview_label)
        layout.addLayout(self._frame_row)
        layout.addWidget(self._tileset_button)
        layout.addWidget(self._play_button)
        layout.addWidget(self._auto_locate_button)
        layout.addWidget(self._error_label)
        layout.addWidget(self._message_label)
        layout.addStretch(1)

        self.clear()

    # --- selection entry points --------------------------------------------------

    def clear(self) -> None:
        self.project = None
        self.entry = None
        self._icon_label.clear()
        self._title_label.clear()
        self._fields_label.clear()
        self._preview_label.clear()
        self._error_label.clear()
        self._frame_row_visible(False)
        self._tileset_button.setVisible(False)
        self._play_button.setVisible(False)
        self._auto_locate_button.setVisible(False)
        self._message_label.setText(_PLACEHOLDER_TEXT)
        self._message_label.setVisible(True)

    def show_path(self, project, path: str) -> None:
        """Show the asset whose source matches ``path``, or clear if it isn't one."""
        entry = next((e for e in project.assets() if e.source == path), None)
        if entry is None:
            self.clear()
            return
        self.show_asset(project, entry)

    def show_asset_id(self, project, asset_id: str) -> None:
        entry = next((e for e in project.assets() if e.id == asset_id), None)
        if entry is None:
            self.clear()
            return
        self.show_asset(project, entry)

    def show_asset(self, project, entry) -> None:
        self.project = project
        self.entry = entry
        self._message_label.setVisible(False)
        self._error_label.clear()

        self._icon_label.setPixmap(icon_for_kind(entry.kind).pixmap(16, 16))
        self._title_label.setText(entry.symbol)

        placement = (
            f"{entry.placement['bank']}:{entry.placement['offset']:#06x}"
            if isinstance(entry.placement, dict)
            else "auto (not yet placed)"
        )
        length = cached_length(project, entry)
        size_text = f"{length} bytes" if length is not None else "not yet built"
        self._fields_label.setText(
            f"kind: {entry.kind.value}\nsource: {entry.source}\nplacement: {placement}\nsize: {size_text}"
        )
        self._auto_locate_button.setVisible(entry.placement == "auto")
        self._play_button.setVisible(entry.kind is AssetKind.BEEPER_SFX)

        self._render_preview()

    # --- preview ------------------------------------------------------------------

    def _render_preview(self) -> None:
        entry = self.entry
        if entry is None:
            return
        self._preview_label.clear()
        self._frame_row_visible(False)
        self._tileset_button.setVisible(False)

        def read_bytes(rel_path: str) -> bytes:
            return (self.project.folder / rel_path).read_bytes()

        try:
            if entry.kind is AssetKind.BITMAP:
                result = convert_asset(entry, read_bytes=read_bytes)
                self._show_bitmap(result)
            elif entry.kind in (AssetKind.SPRITE_SHEET, AssetKind.SPRITE_SEQUENCE):
                result = convert_asset(entry, read_bytes=read_bytes)
                self._show_frame_sequence(result, scrub=True)
            elif entry.kind is AssetKind.FONT:
                result = convert_asset(entry, read_bytes=read_bytes)
                self._show_sheet(result)
            elif entry.kind is AssetKind.TILEMAP:
                self._show_tilemap(read_bytes)
            # binary / pt3 / beeper_sfx: no visual preview, fields above are enough.
        except Exception as exc:  # noqa: BLE001 -- a broken asset must not crash the panel
            self._error_label.setText(f"Couldn't preview this asset: {exc}")

    def _show_bitmap(self, screen_bytes: bytes) -> None:
        buffer = bytearray(SCREEN_WIDTH * SCREEN_HEIGHT * 3)
        for y in range(SCREEN_HEIGHT):
            for x_byte in range(SCREEN_WIDTH // 8):
                bitmap_byte = screen_bytes[bitmap_offset(y, x_byte)]
                attr_byte = screen_bytes[6144 + attribute_offset(y, x_byte)]
                ink, paper = attr_colors(attr_byte)
                for bit in range(8):
                    color = ink if (bitmap_byte & (0x80 >> bit)) else paper
                    o = (y * SCREEN_WIDTH + x_byte * 8 + bit) * 3
                    buffer[o : o + 3] = bytes(color)
        pixmap = _rgb_to_pixmap(buffer, SCREEN_WIDTH, SCREEN_HEIGHT, scale=1)
        self._preview_label.setPixmap(pixmap)

    def _show_frame_sequence(self, sequence: FrameSequence, scrub: bool) -> None:
        if scrub and sequence.frame_count > 1:
            self._frame_spin.blockSignals(True)
            self._frame_spin.setRange(0, sequence.frame_count - 1)
            self._frame_spin.blockSignals(False)
            self._frame_row_visible(True)
        index = min(self._frame_spin.value(), sequence.frame_count - 1)
        rgb = asset_preview.render_sequence_frame_rgb(sequence, index)
        scale = max(_MIN_PREVIEW_SCALE, 128 // max(sequence.frame_width, sequence.frame_height))
        self._preview_label.setPixmap(_rgb_to_pixmap(rgb, sequence.frame_width, sequence.frame_height, scale))

    def _show_sheet(self, sequence: FrameSequence) -> None:
        rgb, width, height = asset_preview.render_sheet_rgb(sequence)
        scale = max(2, 256 // max(width, height))
        self._preview_label.setPixmap(_rgb_to_pixmap(rgb, width, height, scale))

    def _show_tilemap(self, read_bytes) -> None:
        tilemap = parse_tilemap_json(json.loads(read_bytes(self.entry.source)))
        tileset_entry = next((e for e in self.project.assets() if e.symbol == tilemap.tileset_symbol), None)
        if tileset_entry is None:
            raise ValueError(f"tileset '{tilemap.tileset_symbol}' not found")
        tileset = convert_asset(tileset_entry, read_bytes=read_bytes)
        rgb, width, height = asset_preview.render_tilemap_rgb(tilemap, tileset)
        scale = max(1, 512 // max(width, height))
        self._preview_label.setPixmap(_rgb_to_pixmap(rgb, width, height, scale))
        self._tileset_button.setText(f"tileset: {tilemap.tileset_symbol}  →")
        self._tileset_button.setVisible(True)

    def _frame_row_visible(self, visible: bool) -> None:
        self._frame_spin.setVisible(visible)

    # --- actions --------------------------------------------------------------

    def _goto_tileset(self) -> None:
        if self.entry is None or self.project is None:
            return
        try:
            tilemap = parse_tilemap_json(json.loads((self.project.folder / self.entry.source).read_text()))
            tileset_entry = next((e for e in self.project.assets() if e.symbol == tilemap.tileset_symbol), None)
        except Exception as exc:  # noqa: BLE001 -- a broken tilemap must not crash the panel
            self._error_label.setText(f"Couldn't jump to the tileset: {exc}")
            return
        if tileset_entry is not None:
            self.show_asset(self.project, tileset_entry)

    def _auto_locate(self) -> None:
        if self.entry is None or self.project is None:
            return
        auto_locate_one(self.project, self.entry.id)
        self.show_asset_id(self.project, self.entry.id)

    def _play_beeper_sfx(self) -> None:
        if self.entry is None or self.project is None:
            return
        try:
            text = (self.project.folder / self.entry.source).read_text(encoding="utf-8")
            entries = parse_beeper_sfx(text)
            samples = render_tone_sequence(entries)
        except Exception as exc:  # noqa: BLE001 -- a broken sfx file must not crash the panel
            self._error_label.setText(f"Couldn't play this sound: {exc}")
            return
        if not samples:
            return
        sample_rate = 44100
        # Sized to hold the whole clip in one buffer (capped at _MAX_PREVIEW_SECONDS) --
        # a one-shot preview, not the frame-synced streaming the live emulator does, so
        # there's no per-frame feed loop to keep the device topped up.
        clip_ms = min(_MAX_PREVIEW_SECONDS * 1000, int(len(samples) / sample_rate * 1000) + 200)
        self._preview_audio = AudioOutput(sample_rate, buffer_ms=clip_ms)
        self._preview_audio.push(samples)
