"""MemoryCellsView -- a live hex dump of the machine's memory.

The detail counterpart to the visual memory map: where the map answers "what lives
where", this shows the actual bytes. It reads ``machine.memory`` each frame and
renders a window of rows (16 bytes each) as address + hex + ASCII, the familiar
hex-editor shape.

A "Follow PC" toggle keeps the window centred on the program counter while
single-stepping; otherwise you type a base address. The PC and SP rows are marked
in the gutter so you can see the stack and the current instruction at a glance.
Read-only for now (editing bytes is a later step); skips work when hidden.
"""

from __future__ import annotations

from PyQt5.QtGui import QRegExpValidator
from PyQt5.QtCore import QRegExp
from PyQt5.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from zxemu_ui.theme import monospace_font

ROWS = 16          # rows shown
BYTES_PER_ROW = 16


class MemoryCellsView(QWidget):
    """Address + hex + ASCII dump of a window of memory, refreshed each frame."""

    def __init__(self, machine, parent=None):
        super().__init__(parent)
        self.machine = machine
        self._base = 0x4000  # start at the screen/RAM boundary -- somewhere interesting

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Addr"))
        self._addr_edit = QLineEdit(f"{self._base:04X}")
        self._addr_edit.setMaximumWidth(70)
        self._addr_edit.setValidator(QRegExpValidator(QRegExp("[0-9A-Fa-f]{1,4}")))
        self._addr_edit.editingFinished.connect(self._on_addr_edited)
        bar.addWidget(self._addr_edit)
        self._follow_pc = QCheckBox("Follow PC")
        bar.addWidget(self._follow_pc)
        bar.addStretch(1)
        root.addLayout(bar)

        self._dump = QPlainTextEdit()
        self._dump.setReadOnly(True)
        self._dump.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._dump.setFont(monospace_font())
        root.addWidget(self._dump, 1)

        self.refresh()

    def _on_addr_edited(self) -> None:
        text = self._addr_edit.text().strip()
        if text:
            self._base = int(text, 16) & 0xFFF0
            self._follow_pc.setChecked(False)
            self.refresh(force=True)

    def refresh(self, frame_count: int | None = None, force: bool = False) -> None:
        if not force and not self.isVisible():
            return
        memory = self.machine.memory
        pc = self.machine.cpu.regs.pc
        sp = self.machine.cpu.regs.sp
        base = (pc & 0xFFF0) if self._follow_pc.isChecked() else self._base
        if self._follow_pc.isChecked():
            self._addr_edit.setText(f"{base:04X}")

        lines = []
        for row in range(ROWS):
            addr = (base + row * BYTES_PER_ROW) & 0xFFFF
            marker = ">" if addr <= pc < addr + BYTES_PER_ROW else ("S" if addr <= sp < addr + BYTES_PER_ROW else " ")
            values = [memory.read_byte((addr + i) & 0xFFFF) for i in range(BYTES_PER_ROW)]
            hex_part = " ".join(f"{b:02X}" for b in values)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in values)
            lines.append(f"{marker}{addr:04X}  {hex_part}  {ascii_part}")
        self._dump.setPlainText("\n".join(lines))

    def set_mono_scale(self, scale: float) -> None:
        self._dump.setFont(monospace_font(scale))
