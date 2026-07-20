"""MemoryMapView -- the visual, bank-oriented overview of memory.

The centrepiece of the "where did my bytes go?" story. It draws the four 16K slots
as columns, coloured by what occupies them, so free space, the screen region, ROM,
and (later) placed assets are visible at a glance -- the overview you read before
diving into the hex cells for detail.

It is deliberately *bank-oriented* (one column per slot, ROM/RAM labelled) rather
than a flat 64K strip, because that is the model that survives 128K paging: an
asset lives in a bank, not merely at a 16-bit address. Region classification is
basic for now (ROM / screen / RAM); real code/asset/free shading arrives with the
project + build. PC and SP are drawn live as markers so you can watch execution and
the stack move. Repaints only when visible.
"""

from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QPainter
from PyQt5.QtWidgets import QWidget

from zxemu_core.memory import BANK_SIZE

_BG = QColor("#2b2b2b")
_BORDER = QColor("#404040")
_MUTED = QColor("#9aa0a6")
_ROM = QColor("#3a3a3a")
_ROM_HATCH = QColor("#555555")
_RAM = QColor("#2f2f2f")
_SCREEN = QColor("#7a5aa6")
_CONTENDED = QColor("#3a3550")  # faint tint marking contended RAM
_PC = QColor("#e0a13a")
_SP = QColor("#4ec96b")

SCREEN_BYTES = 6912  # bitmap (6144) + attributes (768), at the base of the screen bank
SCREEN_SLOT = 1      # 0x4000 lives in slot 1


class MemoryMapView(QWidget):
    """Four slot columns coloured by region, with live PC/SP markers."""

    def __init__(self, machine, parent=None):
        super().__init__(parent)
        self.machine = machine
        self.setMinimumHeight(140)

    def refresh(self, frame_count: int | None = None) -> None:
        if self.isVisible():
            self.update()  # schedule a repaint

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, _BG)

        margin, label_h, legend_h, gap = 12, 18, 20, 8
        slots = self.machine.memory.slots
        cols = len(slots)
        bar_top = margin + label_h
        bar_bottom = h - margin - legend_h
        bar_h = max(1, bar_bottom - bar_top)
        col_w = (w - 2 * margin - (cols - 1) * gap) / cols

        for i, bank in enumerate(slots):
            x = margin + i * (col_w + gap)
            self._draw_slot_label(p, i, bank, x, margin, col_w, label_h)
            self._draw_slot_bar(p, i, bank, QRectF(x, bar_top, col_w, bar_h))

        self._draw_marker(p, self.machine.cpu.regs.pc, "PC", _PC, margin, gap, col_w, bar_top, bar_h)
        self._draw_marker(p, self.machine.cpu.regs.sp, "SP", _SP, margin, gap, col_w, bar_top, bar_h)
        self._draw_legend(p, margin, h - margin - legend_h + 2, w)

    def _draw_slot_label(self, p, i, bank, x, y, col_w, label_h) -> None:
        kind = "ROM" if bank.readonly else "RAM"
        p.setPen(_MUTED)
        p.drawText(QRectF(x, y, col_w, label_h), Qt.AlignCenter, f"slot {i} · {kind}")

    def _draw_slot_bar(self, p, i, bank, rect: QRectF) -> None:
        if bank.readonly:
            p.fillRect(rect, _ROM)
            p.fillRect(rect, QBrush(_ROM_HATCH, Qt.BDiagPattern))
        else:
            p.fillRect(rect, _CONTENDED if bank.contended else _RAM)
            if i == SCREEN_SLOT:  # the display file sits at the base of this bank
                screen_h = rect.height() * (SCREEN_BYTES / BANK_SIZE)
                p.fillRect(QRectF(rect.x(), rect.y(), rect.width(), screen_h), _SCREEN)
        p.setPen(_BORDER)
        p.drawRect(rect)

    def _draw_marker(self, p, address, label, color, margin, gap, col_w, bar_top, bar_h) -> None:
        slot, offset = divmod(address & 0xFFFF, BANK_SIZE)
        x = margin + slot * (col_w + gap)
        y = bar_top + (offset / BANK_SIZE) * bar_h
        p.setPen(color)
        p.drawLine(int(x), int(y), int(x + col_w), int(y))
        p.drawText(QRectF(x, y - 13, col_w - 2, 12), Qt.AlignRight | Qt.AlignVCenter, f"{label} {address:04X}")

    def _draw_legend(self, p, x, y, w) -> None:
        items = [("ROM", _ROM), ("screen", _SCREEN), ("RAM", _RAM)]
        p.setPen(_MUTED)
        cursor = x
        for name, color in items:
            p.fillRect(QRectF(cursor, y + 3, 11, 11), color)
            cursor += 16
            p.drawText(QRectF(cursor, y, 60, 18), Qt.AlignLeft | Qt.AlignVCenter, name)
            cursor += 60
