"""SpriteEditorView -- draw a sprite pixel-by-pixel and attribute-cell-by-cell.

Works directly on a project's ``.zxspr.json`` file (see
``zxemu_core.assets.native_sprite`` for the format and why it exists rather than
round-tripping through a BMP). Every click writes the whole file back to disk
immediately -- sprite files are tiny, so there's no reason to introduce a separate
dirty/save flow the rest of the asset system doesn't have (``project.add_asset`` and
friends already write straight through).

The core idea the toolbar enforces, matching real hardware: **painting a pixel always
claims its whole 8x8 cell for the currently selected ink/paper/bright**, exactly as if
you'd just repainted that cell's attribute. That's what makes the 2-colours-per-cell
limit a natural consequence of the tool rather than a rule you can accidentally break --
there is no way to *set* a third colour into a cell, because every paint action also
(re)writes that cell's attribute to the one colour pair currently selected.
"""

from __future__ import annotations

import json

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from zxemu_core.assets.palette import BRIGHT_RGB, NORMAL_RGB
from zxemu_core.assets.native_sprite import NATIVE_SUFFIX, blank_sprite_data

PIXEL_SIZE = 24  # on-screen pixels per sprite pixel
_GRID_LINE = QColor("#404040")
_CELL_LINE = QColor("#e0a13a")  # a warm highlight so 8x8 attribute-cell boundaries stand out


class _PaletteRow(QWidget):
    """One row of 8 colour swatches (either the normal or bright half of the palette)."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.selected_index = 0
        self._buttons: list[QPushButton] = []
        self._table = NORMAL_RGB

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(QLabel(label))
        group = QButtonGroup(self)
        group.setExclusive(True)
        for i in range(8):
            button = QPushButton()
            button.setFixedSize(22, 22)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, idx=i: self._select(idx))
            layout.addWidget(button)
            group.addButton(button)
            self._buttons.append(button)
        self._buttons[0].setChecked(True)
        layout.addStretch(1)
        self._refresh_colors()

    def _select(self, index: int) -> None:
        self.selected_index = index

    def set_bright(self, bright: bool) -> None:
        self._table = BRIGHT_RGB if bright else NORMAL_RGB
        self._refresh_colors()

    def _refresh_colors(self) -> None:
        for i, button in enumerate(self._buttons):
            r, g, b = self._table[i]
            button.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 2px solid #222;")


class _SpriteCanvas(QWidget):
    """The pixel grid: click paints a pixel and claims its cell's attribute."""

    def __init__(self, editor: "SpriteEditorView", parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setMouseTracking(False)

    def _frame(self) -> dict | None:
        if self.editor.data is None:
            return None
        return self.editor.data["frames"][self.editor.frame_index]

    def sizeHint(self):
        from PyQt5.QtCore import QSize

        if self.editor.data is None:
            return QSize(200, 200)
        return QSize(self.editor.data["frame_width"] * PIXEL_SIZE, self.editor.data["frame_height"] * PIXEL_SIZE)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        frame = self._frame()
        if frame is None:
            return
        data = self.editor.data
        width, height = data["frame_width"], data["frame_height"]
        attr_cols = width // 8

        for cell_y in range(height // 8):
            for cell_x in range(attr_cols):
                cell = frame["attrs"][cell_y * attr_cols + cell_x]
                table = BRIGHT_RGB if cell["bright"] else NORMAL_RGB
                ink_rgb, paper_rgb = table[cell["ink"]], table[cell["paper"]]
                for dy in range(8):
                    row = frame["pixels"][cell_y * 8 + dy]
                    for dx in range(8):
                        x, y = cell_x * 8 + dx, cell_y * 8 + dy
                        rgb = ink_rgb if row[x] != "." else paper_rgb
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

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.editor.data is None or event.button() not in (Qt.LeftButton, Qt.RightButton):
            return
        x, y = int(event.x() // PIXEL_SIZE), int(event.y() // PIXEL_SIZE)
        data = self.editor.data
        if not (0 <= x < data["frame_width"] and 0 <= y < data["frame_height"]):
            return
        self.editor.paint_pixel(x, y, ink=(event.button() == Qt.LeftButton))
        self.update()


class SpriteEditorView(QWidget):
    """Dockable panel: palette + frame navigation + the pixel canvas, over a ``.zxspr.json`` asset."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.entry = None
        self.data: dict | None = None
        self.frame_index = 0

        self._ink_row = _PaletteRow("Ink:")
        self._paper_row = _PaletteRow("Paper:")
        self._paper_row._buttons[7].setChecked(True)
        self._paper_row.selected_index = 7
        self._bright_check = QCheckBox("Bright")
        self._bright_check.toggled.connect(self._on_bright_toggled)

        self._frame_spin = QSpinBox()
        self._frame_spin.setPrefix("frame ")
        self._frame_spin.valueChanged.connect(self._on_frame_changed)

        self._title_label = QLabel("No sprite open.")
        self._title_label.setStyleSheet("font-weight: bold;")

        self.canvas = _SpriteCanvas(self)

        frame_row = QHBoxLayout()
        frame_row.addWidget(self._frame_spin)
        frame_row.addWidget(self._bright_check)
        frame_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_label)
        layout.addWidget(self._ink_row)
        layout.addWidget(self._paper_row)
        layout.addLayout(frame_row)
        layout.addWidget(self.canvas)
        layout.addStretch(1)

    # --- loading -------------------------------------------------------------

    def show_asset(self, project, entry) -> None:
        self.project = project
        self.entry = entry
        path = project.folder / entry.source
        self.data = json.loads(path.read_text(encoding="utf-8"))
        self.frame_index = 0
        self._frame_spin.blockSignals(True)
        self._frame_spin.setRange(0, len(self.data["frames"]) - 1)
        self._frame_spin.setValue(0)
        self._frame_spin.blockSignals(False)
        self._title_label.setText(entry.symbol)
        self.canvas.updateGeometry()
        self.canvas.update()

    def _on_frame_changed(self, value: int) -> None:
        self.frame_index = value
        self.canvas.update()

    def _on_bright_toggled(self, checked: bool) -> None:
        self._ink_row.set_bright(checked)
        self._paper_row.set_bright(checked)

    # --- editing ---------------------------------------------------------------

    def paint_pixel(self, x: int, y: int, ink: bool) -> None:
        """Set pixel (x, y) in the current frame, and claim its 8x8 cell's attribute
        for whatever ink/paper/bright is currently selected on the toolbar."""
        if self.data is None:
            return
        frame = self.data["frames"][self.frame_index]
        row = frame["pixels"][y]
        frame["pixels"][y] = row[:x] + ("#" if ink else ".") + row[x + 1 :]

        attr_cols = self.data["frame_width"] // 8
        cell_index = (y // 8) * attr_cols + (x // 8)
        frame["attrs"][cell_index] = {
            "ink": self._ink_row.selected_index,
            "paper": self._paper_row.selected_index,
            "bright": self._bright_check.isChecked(),
        }
        self._save()

    def _save(self) -> None:
        if self.project is None or self.entry is None:
            return
        path = self.project.folder / self.entry.source
        path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
