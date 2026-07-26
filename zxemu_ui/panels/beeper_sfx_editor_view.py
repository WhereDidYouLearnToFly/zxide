"""BeeperSfxEditorView -- draw a beeper sound effect as bars of frequency over time.

The underlying ``.zxsfx`` file is a table of (period, duration) pairs
(``zxemu_core.assets.beeper_sfx``), and the first version of this panel showed exactly
that: a column of spin boxes in Hz and frames. Honest, and unusable -- an effect is a
*shape over time*, and no one hears a shape by reading a column of numbers.

So the panel draws the table as a bar chart of the sound:

    freq │           ██
         │        ██ ██
         │  ██    ██ ██ ██
         │  ██ ██ ██ ██ ██
         └──────────────────▶ time

**Each bar rises from the baseline. Its height is the frequency, its width is how long
that frequency sounds.** Drag up for a higher tone, drag sideways to hold it longer, and
the shape you draw is the shape you hear -- which is the whole reason for drawing it at
all. Right-drag erases back to silence.

**One column is one video frame (20ms), the finest thing the format can express, and there
is no setting for that.** An earlier version made the column a configurable "step" of
several frames, which turned out to be a control that earned nothing: length already comes
from how far you drag, so the step only decided the *floor* -- and the right floor is
simply the smallest sound there is. A knob you have to understand before you can draw is
the worst kind, and this one was answering a question the drag already answers.

Because a drag is sampled at whatever rate the mouse reports, moving quickly would skip
whole frames and leave a comb of gaps behind. Every stroke therefore fills in the frames
*between* the last position and this one, interpolating the pitch across them, so a fast
diagonal drag draws a smooth sweep rather than a dotted one.

An earlier version of this panel was a musical piano roll: semitone rows, a piano keyboard
down the side, pitches snapping to notes. It was strictly more machinery for strictly less
-- a beeper effect is a swoop or a thud, not a melody, and snapping a swoop to the
chromatic scale fights it. Frequency here is free and continuous.

**The vertical axis is logarithmic**, one octave per equal step. A linear frequency axis
would squash everything below 500Hz into the bottom eighth of the panel, and low
frequencies are where thuds, rumbles and engine noises live -- the half of the range a
linear axis makes unusable is the half an effect most often needs.

A run of equal periods is drawn as one bar, which is also exactly what it will be in the
saved file, so what you see as one bar really is one entry. Every edit autosaves when the
stroke ends, matching the sprite editor's and the rest of the asset system's "writes
straight through" convention.

That one-bar-one-entry correspondence is also why the summary line reports the **compiled
size in bytes** beside the duration: a held tone costs the same three bytes whether it
lasts one frame or a hundred, while a sweep spends three bytes per frame it changes on. So
the price of a shape isn't visible in the shape, and on a machine with 48K it is the number
that decides whether the effect can stay.
"""

from __future__ import annotations

import math

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from zxemu_core.assets.beeper_sfx import (
    ENTRY_BYTES,
    REST,
    SENTINEL_BYTES,
    expand_to_frames,
    format_beeper_sfx,
    hz_to_period,
    pack_frames,
    parse_beeper_sfx,
    period_to_hz,
    table_size,
)
from zxemu_core.sound.beeper_preview import render_tone_sequence
from zxemu_ui.audio_output import AudioOutput

# Sized to hold a whole preview clip in one buffer -- a one-shot play, not the
# frame-synced streaming the live emulator does, so capped defensively rather than
# ever needing a per-frame feed loop.
_MAX_PREVIEW_SECONDS = 10

FRAMES_PER_SECOND = 50  # a duration is counted in video frames, so this turns it into time

# The frequency axis: seven octaves, 32Hz to 4096Hz, each octave the same height. The
# beeper can reach further either way (the period is 16-bit), but below ~30Hz it is a
# rattle rather than a tone and above ~4kHz there is little left to distinguish.
MIN_HZ = 32.0
OCTAVES = 7
MAX_HZ = MIN_HZ * (2 ** OCTAVES)  # 4096
OCTAVE_HEIGHT = 56
GRID_HEIGHT = OCTAVES * OCTAVE_HEIGHT  # short enough to need no vertical scrolling

# One frame per column, drawn wide enough to be a bar rather than a line. Twelve pixels
# means the shortest possible sound -- a single 20ms frame -- is still a solid block you
# can see and hit, which is the whole point of drawing this as bars. It costs horizontal
# room (a second of audio is 600px), but that is what scrolling is for, and an effect is
# rarely more than a second or two long.
FRAME_WIDTH = 12
AXIS_WIDTH = 52      # the frequency scale down the left
RULER_HEIGHT = 18    # the time scale across the top
MIN_FRAMES = 60      # always offer a second or so of room to draw into
TRAILING_FRAMES = 15  # ...and always a little past the end of the effect
TICK_FRAMES = 5      # a lighter gridline every 100ms, to judge length against

_BACKGROUND = QColor("#1a1a1a")
_GRID = QColor("#242424")
_OCTAVE_LINE = QColor("#333333")
_SECOND_LINE = QColor("#4a4a4a")
_BASELINE = QColor("#5a5a5a")
_BAR = QColor("#3d7fd0")
_BAR_TOP = QColor("#9fccff")   # a lit cap, so the height a bar reaches is unambiguous
_BAR_EDGE = QColor("#12365e")
_AXIS_BG = QColor("#202020")
_AXIS_TEXT = QColor("#9aa0a6")
_RULER_BG = QColor("#222222")
_RULER_TEXT = QColor("#9aa0a6")


def y_for_hz(hz: float) -> float:
    """Where a frequency sits vertically -- log scale, so every octave is the same height."""
    fraction = math.log2(max(MIN_HZ, min(MAX_HZ, hz)) / MIN_HZ) / OCTAVES
    return RULER_HEIGHT + GRID_HEIGHT - fraction * GRID_HEIGHT


def hz_for_y(y: float) -> float:
    """The inverse: a point on the axis back to a frequency."""
    fraction = (RULER_HEIGHT + GRID_HEIGHT - y) / GRID_HEIGHT
    return MIN_HZ * (2 ** (max(0.0, min(1.0, fraction)) * OCTAVES))


def octave_frequencies() -> list[float]:
    """The labelled gridlines: 32, 64, 128 ... 4096."""
    return [MIN_HZ * (2 ** octave) for octave in range(OCTAVES + 1)]


def format_hz(hz: float) -> str:
    return "{:.1f}k".format(hz / 1000) if hz >= 1000 else "{:.0f}".format(hz)


class _BarChart(QWidget):
    """The chart itself: paints the axes and bars, and turns drags into edits."""

    def __init__(self, editor: "BeeperSfxEditorView", parent=None):
        super().__init__(parent)
        self.editor = editor
        self._erasing = False
        self._locked_hz: float | None = None  # pitch held for the length of one stroke
        self._last_frame: int | None = None   # for filling the gap a fast drag jumps over
        self._last_y = 0.0

    # --- geometry --------------------------------------------------------------

    def frame_count(self) -> int:
        used = len(self.editor.columns) + TRAILING_FRAMES
        # Also enough to fill the viewport: a grid that stops halfway across the panel
        # looks like it failed to draw rather than like empty time you can use.
        fit = math.ceil(max(0, self.editor.viewport_width() - AXIS_WIDTH) / FRAME_WIDTH)
        return max(MIN_FRAMES, used, fit)

    def grid_width(self) -> int:
        return self.frame_count() * FRAME_WIDTH

    def baseline_y(self) -> int:
        return RULER_HEIGHT + GRID_HEIGHT

    def x_for_frame(self, frame: int) -> int:
        return AXIS_WIDTH + frame * FRAME_WIDTH

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(AXIS_WIDTH + self.grid_width(), RULER_HEIGHT + GRID_HEIGHT + 1)

    def _origin(self) -> tuple[int, int]:
        """The scrolled-to point, so the axis and ruler can be pinned to the viewport.

        Both are headers: a frequency scale that slides off the left when you scroll right
        is a label for something you can no longer see. Painting them at the current scroll
        offset freezes them without splitting the chart into three synchronised widgets.
        """
        return self.editor.scroll_origin()

    def _frame_at(self, x: int, y: int) -> int | None:
        """Pixel position -> the frame it lands in, or None outside the drawable grid."""
        origin_x, origin_y = self._origin()
        # The pinned axis and ruler sit over the grid; they are labels, not surfaces.
        if x < max(AXIS_WIDTH, origin_x + AXIS_WIDTH) or y < max(RULER_HEIGHT, origin_y + RULER_HEIGHT):
            return None
        if y > self.baseline_y():
            return None
        frame = (x - AXIS_WIDTH) // FRAME_WIDTH
        return int(frame) if 0 <= frame < self.frame_count() else None

    def note_runs(self) -> list[tuple[int, int, int]]:
        """The columns grouped into ``(start_frame, frames, period)`` runs, rests dropped.

        Exactly the grouping ``pack_frames`` will do when this is saved.
        """
        columns = self.editor.columns
        runs: list[tuple[int, int, int]] = []
        index = 0
        while index < len(columns):
            period = columns[index]
            end = index
            while end < len(columns) and columns[end] == period:
                end += 1
            if period != REST:
                runs.append((index, end - index, period))
            index = end
        return runs

    # --- painting --------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), _BACKGROUND)
        self._paint_grid(painter)
        self._paint_bars(painter)
        self._paint_axis(painter)
        self._paint_ruler(painter)

    def _paint_grid(self, painter: QPainter) -> None:
        width = self.grid_width()
        painter.setPen(_OCTAVE_LINE)
        for hz in octave_frequencies():
            y = int(y_for_hz(hz))
            painter.drawLine(AXIS_WIDTH, y, AXIS_WIDTH + width, y)

        # A line per frame would be 50 hairlines a second -- noise, not information. Every
        # 200ms is enough to judge a length against, with the second marks standing out.
        for frame in range(0, self.frame_count() + 1, TICK_FRAMES):
            painter.setPen(_SECOND_LINE if frame % FRAMES_PER_SECOND == 0 else _GRID)
            x = self.x_for_frame(frame)
            painter.drawLine(x, RULER_HEIGHT, x, self.baseline_y())

        painter.setPen(_BASELINE)
        painter.drawLine(AXIS_WIDTH, self.baseline_y(), AXIS_WIDTH + width, self.baseline_y())

    def _visible_seconds(self) -> int:
        return self.frame_count() // FRAMES_PER_SECOND

    def _paint_bars(self, painter: QPainter) -> None:
        baseline = self.baseline_y()
        for start, frames, period in self.note_runs():
            top = int(y_for_hz(period_to_hz(period)))
            left = self.x_for_frame(start)
            width = max(2, frames * FRAME_WIDTH - 1)  # the 1px gap keeps adjacent bars distinct

            painter.setPen(QPen(_BAR_EDGE, 1))
            painter.setBrush(_BAR)
            painter.drawRect(left, top, width, baseline - top)
            # The cap is the whole reading of the chart -- how high this bar got -- so it
            # is drawn brighter than the body rather than left to the fill's top edge.
            painter.fillRect(left + 1, top + 1, max(1, width - 1), 2, _BAR_TOP)

    def _paint_axis(self, painter: QPainter) -> None:
        left, _origin_y = self._origin()  # pinned horizontally
        painter.fillRect(left, RULER_HEIGHT, AXIS_WIDTH, GRID_HEIGHT + 1, _AXIS_BG)
        font = QFont(painter.font())
        font.setPixelSize(9)
        painter.setFont(font)
        for hz in octave_frequencies():
            y = int(y_for_hz(hz))
            painter.setPen(_OCTAVE_LINE)
            painter.drawLine(left + AXIS_WIDTH - 4, y, left + AXIS_WIDTH, y)
            painter.setPen(_AXIS_TEXT)
            # The end labels sit exactly on the top and bottom edges, so centring the text
            # on the line would put half of each behind the ruler or off the widget.
            label_y = max(RULER_HEIGHT, min(y - 8, self.baseline_y() - 16))
            painter.drawText(left, label_y, AXIS_WIDTH - 7, 16,
                             Qt.AlignRight | Qt.AlignVCenter, format_hz(hz))
        painter.setPen(_BASELINE)
        painter.drawLine(left + AXIS_WIDTH - 1, RULER_HEIGHT, left + AXIS_WIDTH - 1, self.baseline_y())

    def _paint_ruler(self, painter: QPainter) -> None:
        _origin_x, top = self._origin()  # pinned vertically
        width = AXIS_WIDTH + self.grid_width()
        painter.fillRect(0, top, width, RULER_HEIGHT, _RULER_BG)
        font = QFont(painter.font())
        font.setPixelSize(9)
        painter.setFont(font)
        for second in range(self._visible_seconds() + 1):
            x = self.x_for_frame(second * FRAMES_PER_SECOND)
            painter.setPen(_SECOND_LINE)
            painter.drawLine(x, top + RULER_HEIGHT - 8, x, top + RULER_HEIGHT)
            painter.setPen(_RULER_TEXT)
            painter.drawText(x + 3, top, 40, RULER_HEIGHT, Qt.AlignLeft | Qt.AlignVCenter, "{}s".format(second))
        painter.setPen(_OCTAVE_LINE)
        painter.drawLine(0, top + RULER_HEIGHT - 1, width, top + RULER_HEIGHT - 1)

    # --- editing ---------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() not in (Qt.LeftButton, Qt.RightButton):
            return
        self._erasing = event.button() == Qt.RightButton
        # Shift holds the pitch for the whole stroke, so a sideways drag stays one bar
        # rather than becoming a row of almost-equal ones that a hand can't keep level.
        # Without it a diagonal drag sweeps, which is the other thing you want to draw.
        self._locked_hz = hz_for_y(event.y()) if event.modifiers() & Qt.ShiftModifier else None
        self._last_frame = None
        self._apply(event.x(), event.y())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & (Qt.LeftButton | Qt.RightButton):
            self._apply(event.x(), event.y())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        # One write per stroke: dragging a two-second sweep would otherwise rewrite the
        # file a hundred times over.
        self._locked_hz = None
        self._last_frame = None
        self.editor.save()

    def _apply(self, x: int, y: int) -> None:
        frame = self._frame_at(x, y)
        if frame is None:
            return
        if self._last_frame is None or frame == self._last_frame:
            self._paint_frame(frame, y)
        else:
            # Fill everything the pointer skipped over, interpolating the pitch so a fast
            # diagonal drag is a smooth sweep rather than a row of disconnected bars.
            direction = 1 if frame > self._last_frame else -1
            span = abs(frame - self._last_frame)
            for offset in range(1, span + 1):
                fraction = offset / span
                self._paint_frame(
                    self._last_frame + offset * direction,
                    self._last_y + (y - self._last_y) * fraction,
                )
        self._last_frame, self._last_y = frame, float(y)
        self.updateGeometry()
        self.update()

    def _paint_frame(self, frame: int, y: float) -> None:
        if self._erasing:
            self.editor.set_rest(frame)
        else:
            self.editor.set_frequency(frame, self._locked_hz if self._locked_hz else hz_for_y(y))


class BeeperSfxEditorView(QWidget):
    """Dockable panel: a frequency-over-time bar chart over a project's ``.zxsfx`` asset."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.entry = None
        self.columns: list[int] = []  # one beeper period per frame; 0 is silence
        self._preview_audio: AudioOutput | None = None
        # Set before the chart exists: QScrollArea.setWidget asks it for its size hint
        # immediately, and it sizes itself against the viewport.
        self._scroll: QScrollArea | None = None

        self._title_label = QLabel("No sound effect open.")
        self._title_label.setStyleSheet("font-weight: bold;")
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet("color: #9aa0a6;")
        # The byte count is the one number that costs something elsewhere in the program,
        # and where it comes from isn't guessable from the drawing: a bar is one entry
        # however long it is, so holding a tone is free and sweeping is not.
        self._summary_label.setToolTip(
            "Compiled size of this effect in the Spectrum's memory: {} bytes per "
            "entry (a held tone or rest, whatever its length) plus a {}-byte "
            "end marker.".format(ENTRY_BYTES, SENTINEL_BYTES)
        )

        self.chart = _BarChart(self)
        scroll = QScrollArea()
        scroll.setWidget(self.chart)
        scroll.setWidgetResizable(False)
        # Without this the viewport's default panel colour shows through wherever the chart
        # doesn't reach, which reads as a rendering fault rather than as empty space.
        scroll.setStyleSheet("QScrollArea { border: 1px solid #303030; background: #1a1a1a; }")
        scroll.viewport().setStyleSheet("background: #1a1a1a;")
        self._scroll = scroll
        # The axis and ruler are painted at the scroll offset to keep them pinned, so they
        # have to be repainted as it changes -- Qt only moves the widget otherwise.
        scroll.horizontalScrollBar().valueChanged.connect(self.chart.update)
        scroll.verticalScrollBar().valueChanged.connect(self.chart.update)

        self._play_button = QPushButton("▶ Play")
        self._play_button.clicked.connect(self._play)
        self._clear_button = QPushButton("Clear")
        self._clear_button.clicked.connect(self.clear)

        hint = QLabel("Drag up for a higher tone, sideways to make it last longer · "
                      "shift-drag keeps the pitch level · right-drag erases")
        hint.setStyleSheet("color: #6d7276;")

        buttons_row = QHBoxLayout()
        buttons_row.addWidget(self._play_button)
        buttons_row.addWidget(self._clear_button)
        buttons_row.addStretch(1)

        hint_row = QHBoxLayout()
        hint_row.addWidget(hint)
        hint_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_label)
        layout.addWidget(self._summary_label)
        layout.addLayout(buttons_row)
        layout.addLayout(hint_row)
        layout.addWidget(scroll)

    # --- loading -----------------------------------------------------------------

    def show_asset(self, project, entry) -> None:
        self.project = project
        self.entry = entry
        self._title_label.setText(entry.symbol)
        text = (project.folder / entry.source).read_text(encoding="utf-8")
        self.columns = expand_to_frames(parse_beeper_sfx(text))
        self._refresh()

    def scroll_origin(self) -> tuple[int, int]:
        """Where the viewport currently sits over the chart, for pinning its headers."""
        if self._scroll is None:
            return 0, 0
        return self._scroll.horizontalScrollBar().value(), self._scroll.verticalScrollBar().value()

    def viewport_width(self) -> int:
        return self._scroll.viewport().width() if self._scroll is not None else 0

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._scroll is not None:
            self._refresh()  # the grid grows to fill a wider panel

    def _refresh(self) -> None:
        entries = self.entries()
        frames = len(self.columns)
        seconds = frames / FRAMES_PER_SECOND
        self._summary_label.setText(
            "{:.2f}s · {} frame{} · "
            "{} entr{} · "
            "{} bytes".format(seconds, frames, 's' if frames != 1 else '', len(entries), 'y' if len(entries) == 1 else 'ies', table_size(entries))
        )
        self.chart.updateGeometry()
        self.chart.resize(self.chart.sizeHint())
        self.chart.update()

    # --- editing -------------------------------------------------------------------

    def _grow_to(self, frame: int) -> None:
        """Extend the track with silence so ``frame`` exists -- drawing past the end appends."""
        if frame >= len(self.columns):
            self.columns.extend([REST] * (frame + 1 - len(self.columns)))

    def set_frequency(self, frame: int, hz: float, save: bool = False) -> None:
        """Set one frame -- 20ms, the shortest sound there is -- to the tone at ``hz``."""
        self._grow_to(frame)
        self.columns[frame] = hz_to_period(hz)
        self._refresh()
        if save:
            self.save()

    def set_rest(self, frame: int, save: bool = False) -> None:
        """Silence one frame."""
        if frame < len(self.columns):
            self.columns[frame] = REST
            self._refresh()
            if save:
                self.save()

    def clear(self) -> None:
        self.columns = []
        self._refresh()
        self.save()

    def entries(self) -> list[tuple[int, int]]:
        """The (period, duration) table these columns encode -- exactly what gets saved."""
        return pack_frames(list(self.columns))

    # --- persistence and playback -------------------------------------------------

    def save(self) -> None:
        if self.project is None or self.entry is None:
            return
        path = self.project.folder / self.entry.source
        path.write_text(format_beeper_sfx(self.entries()), encoding="utf-8")
        self._refresh()

    # Kept as the old private name too: the panel autosaves from several places and the
    # rest of the codebase (and the tests) already call it that.
    _save = save

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
