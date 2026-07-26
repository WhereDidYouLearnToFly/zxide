"""SpriteEditorView -- draw a sprite pixel-by-pixel, in real ZX colours.

Works directly on a project's native sprite file (see ``zxemu_core.assets.native_sprite``
for the six formats and why they exist rather than round-tripping through a BMP). A
stroke is written back to disk as soon as the mouse comes up -- sprite files are tiny, so
there's no reason to introduce a separate dirty/save flow the rest of the asset system
doesn't have (``project.add_asset`` and friends already write straight through).

**There is one tool, not a mode to switch between.** Drawing a pixel also claims its whole
8x8 cell for the currently selected ink/paper/bright, exactly as if you had repainted that
cell's attribute -- because on this hardware you effectively did. That makes the
two-colours-per-cell limit a natural consequence of drawing rather than a rule you have to
remember, and it means the colour you picked is the colour you get, without a second step.

What that used to cost, and no longer does, is erasing: under the older left-ink /
right-paper scheme, removing a stray pixel meant first switching the selected colour to
whatever that cell's paper was. So the left button **toggles** instead -- press decides the
stroke's value from the pixel under the cursor (on if it was off, off if it was on) and the
drag paints that one value, so dragging back over pixels you just set doesn't undo them.
Erasing is just clicking a pixel that is already on.

The other two buttons are the escape hatches that keep this from being restrictive, and
neither is a mode -- they are things the mouse does, with no state to get stuck in:

    left            draw: toggle the pixel, and claim its cell for the selected colours
    right           recolour only: apply the selected colours to the cell, leave pixels alone
    alt + left      eyedropper: pick the cell's colours back up into the palette

Pixel-only formats (``.zx8x8pix`` and friends) have no attribute plane at all, so for those
the palette is hidden, the canvas draws in black and white, and only the pixel half applies.
"""

from __future__ import annotations

import json

from PyQt5.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from zxemu_core.assets.native_sprite import (
    SpriteDocument,
    attr_byte,
    attr_parts,
    load_sprite_file,
    sprite_format,
    to_legacy_json,
)
from zxemu_core.assets.palette import BRIGHT_RGB, NORMAL_RGB

PIXEL_SIZE = 24  # on-screen pixels per sprite pixel
_GRID_LINE = QColor("#404040")
_CELL_LINE = QColor("#e0a13a")  # a warm highlight so 8x8 attribute-cell boundaries stand out

# The palette bar. A selected swatch is legible two ways at once -- it is drawn markedly
# larger, *and* ringed -- rather than relying on a tint, which would vanish against half of
# a palette that contains both black and white.
#
# The ring is drawn in the cell's margin, outside the colour area, never over it. Drawing it
# on top instead is the obvious thing and it is wrong: a 2px ring inside a small swatch eats
# most of the swatch, so selecting black produced a mostly-white square -- the indicator
# hiding the one thing it was pointing at.
SWATCH_CELL = 30
SELECTED_INSET = 4    # colour area 22x22, with the ring in the 4px margin around it
UNSELECTED_INSET = 7  # colour area 16x16 -- visibly smaller at a glance
_SELECTED_FRAME = QColor("#ffffff")
_SELECTED_EDGE = QColor("#101010")  # a dark ring outside the white one, so white stays visible
_SWATCH_EDGE = QColor("#101010")


class _PaletteBar(QWidget):
    """One row of 8 colour swatches, drawn rather than styled.

    The previous version used checkable ``QPushButton``s with a background-colour
    stylesheet, which silently defeated itself: the stylesheet replaced the whole button
    rendering, so the *checked* state -- the only thing indicating which colour was
    selected -- was never drawn. Painting the row directly means selection is something
    this widget states explicitly instead of hoping the style leaves room for it.
    """

    selection_changed = pyqtSignal()

    def __init__(self, label: str, selected: int = 0, parent=None):
        super().__init__(parent)
        self.selected_index = selected
        self._table = NORMAL_RGB
        self._label = label
        self.setFixedHeight(SWATCH_CELL + 2)
        self.setMinimumWidth(8 * SWATCH_CELL + 2)
        self.setCursor(Qt.PointingHandCursor)

    def set_bright(self, bright: bool) -> None:
        self._table = BRIGHT_RGB if bright else NORMAL_RGB
        self.update()

    def select(self, index: int) -> None:
        if 0 <= index < 8 and index != self.selected_index:
            self.selected_index = index
            self.update()
            self.selection_changed.emit()

    def color(self) -> tuple[int, int, int]:
        return self._table[self.selected_index]

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(8 * SWATCH_CELL + 2, SWATCH_CELL + 2)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        for index in range(8):
            selected = index == self.selected_index
            inset = SELECTED_INSET if selected else UNSELECTED_INSET
            x = index * SWATCH_CELL + inset
            y = inset
            size = SWATCH_CELL - 2 * inset

            painter.setBrush(QColor(*self._table[index]))
            painter.setPen(QPen(_SWATCH_EDGE, 1))
            painter.drawRect(x, y, size, size)

            if selected:
                # Two concentric rings in the margin: white so it reads against a dark
                # swatch, wrapped in near-black so it still reads against a white one.
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(_SELECTED_FRAME, 2))
                painter.drawRect(x - 2, y - 2, size + 4, size + 4)
                painter.setPen(QPen(_SELECTED_EDGE, 1))
                painter.drawRect(x - 4, y - 4, size + 8, size + 8)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.select(int(event.x() // SWATCH_CELL))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton:
            self.select(int(event.x() // SWATCH_CELL))


class _ColorPreview(QWidget):
    """The selected ink and paper shown together, as a cell actually looks.

    Two rows of eight swatches tell you which *entries* are picked; they don't tell you
    what the pair looks like side by side, which is the thing you are choosing. This does
    -- a small tile of paper with an ink shape on it, exactly the two colours the next
    pixel you draw will produce.
    """

    SIZE = 46

    def __init__(self, editor: "SpriteEditorView", parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setToolTip("The ink and paper the next pixel you draw will give its 8x8 cell")

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        ink, paper, bright = attr_parts(self.editor.selected_attr())
        table = BRIGHT_RGB if bright else NORMAL_RGB
        painter.fillRect(self.rect(), QColor(*table[paper]))
        # A blocky ink glyph rather than a plain split: it reads as "this drawn on that",
        # which is what an attribute cell is.
        step = self.SIZE // 8
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(*table[ink]))
        for row, bits in enumerate((0b00111100, 0b01100110, 0b01100110, 0b01111110,
                                    0b01100110, 0b01100110, 0b01100110, 0b00000000)):
            for column in range(8):
                if bits & (0x80 >> column):
                    painter.fillRect(column * step, row * step, step, step, QColor(*table[ink]))
        painter.setPen(QPen(QColor("#101010"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(0, 0, self.SIZE - 1, self.SIZE - 1)


class _SpriteCanvas(QWidget):
    """The pixel grid. Press starts a stroke, drag continues it, release saves it once."""

    def __init__(self, editor: "SpriteEditorView", parent=None):
        super().__init__(parent)
        self.editor = editor
        # Painting continues under a held button, so the canvas must hear moves; tracking
        # stays off, since a move with no button down is not part of any stroke.
        self.setMouseTracking(False)
        self._stroke_value: int | None = None  # the pixel value this drag is painting

    def sizeHint(self) -> QSize:  # noqa: N802
        document = self.editor.document
        if document is None:
            return QSize(200, 200)
        return QSize(document.width * PIXEL_SIZE, document.height * PIXEL_SIZE)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        document = self.editor.document
        if document is None:
            return
        frame = document.frames[self.editor.frame_index]
        width, height = document.width, document.height

        for cell_y in range(document.attr_rows):
            for cell_x in range(document.attr_cols):
                cell = cell_y * document.attr_cols + cell_x
                ink_index, paper_index, bright = attr_parts(document.cell_attr(self.editor.frame_index, cell))
                table = BRIGHT_RGB if bright else NORMAL_RGB
                ink_rgb, paper_rgb = table[ink_index], table[paper_index]
                for dy in range(8):
                    row = frame.pixels[cell_y * 8 + dy]
                    for dx in range(8):
                        x, y = cell_x * 8 + dx, cell_y * 8 + dy
                        rgb = ink_rgb if row[x] else paper_rgb
                        painter.fillRect(
                            QRectF(x * PIXEL_SIZE, y * PIXEL_SIZE, PIXEL_SIZE, PIXEL_SIZE), QColor(*rgb)
                        )

        painter.setPen(_GRID_LINE)
        for x in range(width + 1):
            painter.drawLine(x * PIXEL_SIZE, 0, x * PIXEL_SIZE, height * PIXEL_SIZE)
        for y in range(height + 1):
            painter.drawLine(0, y * PIXEL_SIZE, width * PIXEL_SIZE, y * PIXEL_SIZE)

        painter.setPen(_CELL_LINE)
        for x in range(0, width + 1, 8):
            painter.drawLine(x * PIXEL_SIZE, 0, x * PIXEL_SIZE, height * PIXEL_SIZE)
        for y in range(0, height + 1, 8):
            painter.drawLine(0, y * PIXEL_SIZE, width * PIXEL_SIZE, y * PIXEL_SIZE)

    # --- strokes ---------------------------------------------------------------

    def _cell_at(self, event) -> tuple[int, int] | None:
        document = self.editor.document
        if document is None:
            return None
        x, y = int(event.x() // PIXEL_SIZE), int(event.y() // PIXEL_SIZE)
        if not (0 <= x < document.width and 0 <= y < document.height):
            return None
        return x, y

    def mousePressEvent(self, event) -> None:  # noqa: N802
        position = self._cell_at(event)
        if position is None or event.button() not in (Qt.LeftButton, Qt.RightButton):
            return
        x, y = position
        editor = self.editor

        if event.button() == Qt.LeftButton and event.modifiers() & Qt.AltModifier:
            editor.pick_attribute(x, y)  # eyedropper -- reads, so nothing to save
            self.update()
            return
        if event.button() == Qt.RightButton:
            editor.apply_attribute(x, y, save=False)  # recolour the cell, leave pixels alone
            self.update()
            return

        # The press decides the whole stroke's value, so dragging back over a pixel you
        # just set doesn't flip it off again.
        self._stroke_value = 0 if editor.pixel_at(x, y) else 1
        editor.paint_pixel(x, y, self._stroke_value, save=False)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        position = self._cell_at(event)
        if position is None:
            return
        x, y = position
        if event.buttons() & Qt.RightButton:
            self.editor.apply_attribute(x, y, save=False)
            self.update()
            return
        if self._stroke_value is not None and event.buttons() & Qt.LeftButton:
            self.editor.paint_pixel(x, y, self._stroke_value, save=False)
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        # One write per stroke rather than per pixel: a drag across a 32-wide sprite would
        # otherwise be dozens of rewrites of the same small file.
        self._stroke_value = None
        self.editor.save()


class SpriteEditorView(QWidget):
    """Dockable panel: palette + frame navigation + the pixel canvas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.entry = None
        self.document: SpriteDocument | None = None
        self.frame_index = 0
        self._is_legacy_json = False

        self._ink_bar = _PaletteBar("Ink", selected=0)
        self._paper_bar = _PaletteBar("Paper", selected=7)
        self._bright_check = QCheckBox("Bright")
        self._bright_check.toggled.connect(self._on_bright_toggled)

        self._preview = _ColorPreview(self)
        for bar in (self._ink_bar, self._paper_bar):
            bar.selection_changed.connect(self._preview.update)

        self._ink_label = QLabel("Ink")
        self._paper_label = QLabel("Paper")
        for label in (self._ink_label, self._paper_label):
            label.setFixedWidth(40)

        self._frame_spin = QSpinBox()
        self._frame_spin.setPrefix("frame ")
        self._frame_spin.valueChanged.connect(self._on_frame_changed)

        self._title_label = QLabel("No sprite open.")
        self._title_label.setStyleSheet("font-weight: bold;")
        self._format_label = QLabel("")
        self._format_label.setStyleSheet("color: #9aa0a6;")
        self._hint_label = QLabel(
            "Drag to draw — the selected ink and paper claim that 8×8 cell. "
            "Right-drag recolours only · Alt+click picks a cell's colours up."
        )
        self._hint_label.setStyleSheet("color: #6d7276;")
        self._hint_label.setWordWrap(True)

        self.canvas = _SpriteCanvas(self)

        ink_row = QHBoxLayout()
        ink_row.setSpacing(6)
        ink_row.addWidget(self._ink_label)
        ink_row.addWidget(self._ink_bar)
        ink_row.addStretch(1)

        paper_row = QHBoxLayout()
        paper_row.setSpacing(6)
        paper_row.addWidget(self._paper_label)
        paper_row.addWidget(self._paper_bar)
        paper_row.addStretch(1)

        bars = QVBoxLayout()
        bars.setSpacing(4)
        bars.addLayout(ink_row)
        bars.addLayout(paper_row)

        self._palette_row = QHBoxLayout()
        self._palette_row.addWidget(self._preview)
        self._palette_row.addLayout(bars)
        self._palette_row.addWidget(self._bright_check)
        self._palette_row.addStretch(1)

        frame_row = QHBoxLayout()
        frame_row.addWidget(self._frame_spin)
        frame_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_label)
        layout.addWidget(self._format_label)
        layout.addLayout(self._palette_row)
        layout.addLayout(frame_row)
        layout.addWidget(self.canvas)
        layout.addWidget(self._hint_label)
        layout.addStretch(1)

    # --- loading -------------------------------------------------------------

    def show_asset(self, project, entry) -> None:
        self.project = project
        self.entry = entry
        source = entry.source if isinstance(entry.source, str) else entry.source[0]
        path = project.folder / source
        self.document = load_sprite_file(source, path.read_bytes())
        self._is_legacy_json = sprite_format(source) is None  # i.e. the legacy .zxspr.json
        self.frame_index = 0
        self._frame_spin.blockSignals(True)
        self._frame_spin.setRange(0, len(self.document.frames) - 1)
        self._frame_spin.setValue(0)
        self._frame_spin.blockSignals(False)
        self._title_label.setText(entry.symbol)

        colour = "pixels + attributes" if self.document.has_attrs else "pixels only"
        frames = len(self.document.frames)
        self._format_label.setText(
            "{}x{} · {} frame{} · {}".format(self.document.width, self.document.height, frames, 's' if frames != 1 else '', colour)
        )
        self._apply_colour_mode()
        self.canvas.updateGeometry()
        self.canvas.update()

    def _apply_colour_mode(self) -> None:
        """Hide everything colour-related for a pixel-only sprite -- it has no attributes."""
        has_attrs = bool(self.document and self.document.has_attrs)
        for widget in (self._preview, self._ink_bar, self._paper_bar,
                       self._ink_label, self._paper_label, self._bright_check):
            widget.setVisible(has_attrs)
        self._hint_label.setText(
            "Drag to draw — the selected ink and paper claim that 8×8 cell. "
            "Right-drag recolours only · Alt+click picks a cell's colours up."
            if has_attrs else
            "Drag to draw. This format stores pixels only, so there are no colours to set."
        )

    def _on_frame_changed(self, value: int) -> None:
        self.frame_index = value
        self.canvas.update()

    def _on_bright_toggled(self, checked: bool) -> None:
        self._ink_bar.set_bright(checked)
        self._paper_bar.set_bright(checked)
        self._preview.update()

    # --- editing ---------------------------------------------------------------

    def selected_attr(self) -> int:
        """The attribute byte the palette currently describes."""
        return attr_byte(self._ink_bar.selected_index, self._paper_bar.selected_index,
                         self._bright_check.isChecked())

    def pixel_at(self, x: int, y: int) -> int:
        if self.document is None:
            return 0
        return self.document.frames[self.frame_index].pixels[y][x]

    def paint_pixel(self, x: int, y: int, value: int, save: bool = True) -> None:
        """Set pixel (x, y), and claim its 8x8 cell for the selected ink/paper/bright.

        Both halves are one action on purpose: a pixel and the colours it appears in are
        the same decision on this hardware, and splitting them into two tools only made
        you do the second one by hand.
        """
        if self.document is None:
            return
        self.document.frames[self.frame_index].pixels[y][x] = 1 if value else 0
        self._claim_cell(x, y)
        if save:
            self.save()

    def toggle_pixel(self, x: int, y: int, save: bool = True) -> None:
        """Flip pixel (x, y) -- what a single click does."""
        self.paint_pixel(x, y, 0 if self.pixel_at(x, y) else 1, save=save)

    def apply_attribute(self, x: int, y: int, save: bool = True) -> None:
        """Give the 8x8 cell containing (x, y) the selected colours, without touching pixels."""
        if self.document is None:
            return
        self._claim_cell(x, y)
        if save:
            self.save()

    def _claim_cell(self, x: int, y: int) -> None:
        if not self.document.has_attrs:
            return  # a pixel-only format has no attribute plane to claim
        cell = self.document.cell_index(x, y)
        self.document.frames[self.frame_index].attrs[cell] = self.selected_attr()

    def pick_attribute(self, x: int, y: int) -> None:
        """Eyedropper: load the cell's ink/paper/bright back into the palette."""
        if self.document is None or not self.document.has_attrs:
            return
        cell = self.document.cell_index(x, y)
        ink, paper, bright = attr_parts(self.document.frames[self.frame_index].attrs[cell])
        self._bright_check.setChecked(bright)  # first: it re-tables both palette bars
        self._ink_bar.select(ink)
        self._paper_bar.select(paper)
        self._preview.update()

    # --- persistence -----------------------------------------------------------

    def save(self) -> None:
        if self.project is None or self.entry is None or self.document is None:
            return
        source = self.entry.source if isinstance(self.entry.source, str) else self.entry.source[0]
        path = self.project.folder / source
        if self._is_legacy_json:
            path.write_text(json.dumps(to_legacy_json(self.document), indent=2), encoding="utf-8")
            return
        fmt = sprite_format(source)
        path.write_bytes(self.document.encode(with_header=bool(fmt and fmt.has_header)))
