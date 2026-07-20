"""RegistersView -- a live read-out of the Z80 register file.

A dockable debug panel that mirrors the CPU's registers and flags each frame. It
reads straight from ``machine.cpu.regs`` (the pairs af/bc/de/hl/ix/iy and the
special sp/pc/i/r/im are already exposed there), so it is a pure view -- it never
changes machine state.

Skips its own work when hidden, so a docked-away or tabbed-behind panel costs
nothing.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from zxemu_core.cpu.registers import (
    FLAG_C,
    FLAG_H,
    FLAG_N,
    FLAG_P,
    FLAG_S,
    FLAG_X,
    FLAG_Y,
    FLAG_Z,
)
from zxemu_ui.theme import monospace_font

# Register cells laid out in a grid: (label, attribute-name, hex-width-in-nibbles).
_REG_ROWS = [
    [("AF", "af", 4), ("BC", "bc", 4), ("DE", "de", 4), ("HL", "hl", 4)],
    [("AF'", "af2", 4), ("BC'", "bc2", 4), ("DE'", "de2", 4), ("HL'", "hl2", 4)],
    [("IX", "ix", 4), ("IY", "iy", 4), ("SP", "sp", 4), ("PC", "pc", 4)],
    [("I", "i", 2), ("R", "r", 2), ("IM", "im", 1)],
]

# Flag bits shown left-to-right in the conventional SZ5H3PNC order.
_FLAGS = [("S", FLAG_S), ("Z", FLAG_Z), ("5", FLAG_Y), ("H", FLAG_H),
          ("3", FLAG_X), ("P", FLAG_P), ("N", FLAG_N), ("C", FLAG_C)]


class RegistersView(QWidget):
    """Grid of register values plus a flags strip, refreshed from the CPU each frame."""

    def __init__(self, machine, parent=None):
        super().__init__(parent)
        self.machine = machine
        self._value_labels: dict[str, QLabel] = {}
        self._flag_labels: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        for r, row in enumerate(_REG_ROWS):
            for c, (label, attr, _width) in enumerate(row):
                cell = QLabel()
                cell.setFont(monospace_font())
                cell.setText(f"{label:>3} ----")
                self._value_labels[attr] = cell
                grid.addWidget(cell, r, c)
        root.addLayout(grid)

        flags_row = QGridLayout()
        flags_row.setHorizontalSpacing(6)
        caption = QLabel("flags")
        caption.setStyleSheet("color: palette(mid);")
        flags_row.addWidget(caption, 0, 0)
        for i, (name, _mask) in enumerate(_FLAGS, start=1):
            f = QLabel(name)
            f.setAlignment(Qt.AlignCenter)
            f.setFont(monospace_font())
            f.setStyleSheet("border: 1px solid palette(mid); border-radius: 3px; padding: 1px 4px;")
            self._flag_labels[name] = f
            flags_row.addWidget(f, 0, i)
        flags_row.setColumnStretch(len(_FLAGS) + 1, 1)
        root.addLayout(flags_row)
        root.addStretch(1)

        self.refresh()

    def refresh(self, frame_count: int | None = None) -> None:
        if not self.isVisible():
            return
        regs = self.machine.cpu.regs
        for row in _REG_ROWS:
            for label, attr, width in row:
                self._value_labels[attr].setText(f"{label:>3} {getattr(regs, attr):0{width}X}")
        for name, mask in _FLAGS:
            on = bool(regs.f & mask)
            self._flag_labels[name].setStyleSheet(
                "border-radius: 3px; padding: 1px 4px;"
                + ("border: 1px solid palette(highlight); background: palette(highlight); color: palette(highlighted-text);"
                   if on else "border: 1px solid palette(mid); color: palette(mid);")
            )

    def set_mono_scale(self, scale: float) -> None:
        font = monospace_font(scale)
        for label in (*self._value_labels.values(), *self._flag_labels.values()):
            label.setFont(font)
