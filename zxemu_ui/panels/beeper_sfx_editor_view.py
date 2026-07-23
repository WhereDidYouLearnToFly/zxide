"""BeeperSfxEditorView -- build a beeper sound effect as tones/rests, in Hz and frames.

The underlying ``.zxsfx`` file format (``zxemu_core.assets.beeper_sfx``) is already a
simple, editable shape -- ``period,duration`` pairs, one per line -- so unlike sprites
there's no need for a separate native format here; this panel just reads and writes
that exact text, converting each period to/from a frequency in Hz for display, since a
raw T-state period is not something anyone can read at a glance (``zxemu_core.assets.
beeper_sfx.period_to_hz``/``hz_to_period`` do the conversion). Every edit autosaves
immediately, matching the sprite editor's and the rest of the asset system's "writes
straight through" convention.
"""

from __future__ import annotations

from PyQt5.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

from zxemu_core.assets.beeper_sfx import format_beeper_sfx, hz_to_period, parse_beeper_sfx, period_to_hz
from zxemu_core.sound.beeper_preview import render_tone_sequence
from zxemu_ui.audio_output import AudioOutput

# Sized to hold a whole preview clip in one buffer -- a one-shot play, not the
# frame-synced streaming the live emulator does, so capped defensively rather than
# ever needing a per-frame feed loop.
_MAX_PREVIEW_SECONDS = 10
_DEFAULT_FREQUENCY_HZ = 440.0
_DEFAULT_DURATION_FRAMES = 4


class _EntryRow(QWidget):
    """One (frequency, duration) row: Hz + frames + a remove button."""

    def __init__(self, editor: "BeeperSfxEditorView", frequency_hz: float, duration_frames: int, parent=None):
        super().__init__(parent)
        self.editor = editor

        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setSuffix(" Hz")
        self.freq_spin.setRange(0, 20000)
        self.freq_spin.setDecimals(1)
        self.freq_spin.setValue(frequency_hz)

        self.duration_spin = QSpinBox()
        self.duration_spin.setSuffix(" frames")
        self.duration_spin.setRange(0, 255)
        self.duration_spin.setValue(duration_frames)

        # Connected after the initial setValue calls above, so loading existing
        # values doesn't trigger a spurious autosave before the row is even placed.
        self.freq_spin.valueChanged.connect(editor._save)
        self.duration_spin.valueChanged.connect(editor._save)

        remove_button = QPushButton("✕")
        remove_button.setFixedWidth(28)
        remove_button.clicked.connect(lambda: editor._remove_row(self))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.freq_spin)
        layout.addWidget(self.duration_spin)
        layout.addWidget(remove_button)

    def entry(self) -> tuple[int, int]:
        return hz_to_period(self.freq_spin.value()), self.duration_spin.value()


class BeeperSfxEditorView(QWidget):
    """Dockable panel: rows of tones/rests over a project's ``.zxsfx`` asset."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.entry = None
        self._preview_audio: AudioOutput | None = None

        self._title_label = QLabel("No sound effect open.")
        self._title_label.setStyleSheet("font-weight: bold;")

        self._rows_layout = QVBoxLayout()

        self._add_tone_button = QPushButton("+ Tone")
        self._add_tone_button.clicked.connect(
            lambda: self._add_row(_DEFAULT_FREQUENCY_HZ, _DEFAULT_DURATION_FRAMES)
        )
        self._add_rest_button = QPushButton("+ Rest")
        self._add_rest_button.clicked.connect(lambda: self._add_row(0.0, _DEFAULT_DURATION_FRAMES))
        self._play_button = QPushButton("▶ Play")
        self._play_button.clicked.connect(self._play)

        buttons_row = QHBoxLayout()
        buttons_row.addWidget(self._add_tone_button)
        buttons_row.addWidget(self._add_rest_button)
        buttons_row.addWidget(self._play_button)
        buttons_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_label)
        layout.addLayout(self._rows_layout)
        layout.addLayout(buttons_row)
        layout.addStretch(1)

    # --- loading -----------------------------------------------------------------

    def show_asset(self, project, entry) -> None:
        self.project = project
        self.entry = entry
        self._title_label.setText(entry.symbol)
        self._clear_rows()
        text = (project.folder / entry.source).read_text(encoding="utf-8")
        for period, duration in parse_beeper_sfx(text):
            self._add_row(period_to_hz(period), duration, save=False)

    def _clear_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    # --- rows ----------------------------------------------------------------

    def _rows(self) -> list[_EntryRow]:
        return [self._rows_layout.itemAt(i).widget() for i in range(self._rows_layout.count())]

    def entries(self) -> list[tuple[int, int]]:
        return [row.entry() for row in self._rows()]

    def _add_row(self, frequency_hz: float, duration_frames: int, save: bool = True) -> None:
        self._rows_layout.addWidget(_EntryRow(self, frequency_hz, duration_frames))
        if save:
            self._save()

    def _remove_row(self, row: _EntryRow) -> None:
        self._rows_layout.removeWidget(row)
        row.deleteLater()
        self._save()

    # --- persistence and playback -------------------------------------------------

    def _save(self) -> None:
        if self.project is None or self.entry is None:
            return
        path = self.project.folder / self.entry.source
        path.write_text(format_beeper_sfx(self.entries()), encoding="utf-8")

    def _play(self) -> None:
        entries = self.entries()
        if not entries:
            return
        samples = render_tone_sequence(entries)
        if not samples:
            return
        sample_rate = 44100
        clip_ms = min(_MAX_PREVIEW_SECONDS * 1000, int(len(samples) / sample_rate * 1000) + 200)
        self._preview_audio = AudioOutput(sample_rate, buffer_ms=clip_ms)
        self._preview_audio.push(samples)
