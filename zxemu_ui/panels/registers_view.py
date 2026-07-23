"""RegistersView -- a live read-out of the Z80 register file.

A dockable debug panel that mirrors the CPU's registers and flags each frame,
reading straight from ``machine.cpu.regs`` (the pairs af/bc/de/hl/ix/iy and the
special sp/pc/i/r/im are already exposed there).

Clicking a register lets you *set* it, which is what turns the debugger from a
microscope into a workbench: force a flag to take the other branch, move PC to skip
a call, drop a value in to see what the routine does with it -- all without
rebuilding. Only meaningful while paused; under a running machine the next
instruction would overwrite your change before you saw it.

Below the flags sits a T-state read-out. On a Spectrum, time *is* T-states, so this
is the number you hand-time loops against.

Skips its own work when hidden, so a docked-away or tabbed-behind panel costs
nothing.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QGridLayout, QInputDialog, QLabel, QVBoxLayout, QWidget

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

# Flag bits shown left-to-right in the conventional SZ5H3PNC order, each with what it
# actually means. The flags are the part of the Z80 a learner meets first and
# understands last -- "why did my JR NZ not jump?" is nearly always a flags question --
# so each one carries its explanation as a tooltip rather than assuming you know.
_FLAGS = [
    ("S", FLAG_S, "Sign — set when the result's bit 7 is 1 (i.e. negative as a signed byte)."),
    ("Z", FLAG_Z, "Zero — set when the result was exactly zero. What JR Z / JR NZ test."),
    ("5", FLAG_Y, "Undocumented copy of result bit 5. Real hardware sets it; almost nothing reads it."),
    ("H", FLAG_H, "Half-carry — carry out of bit 3. Used internally by DAA for BCD arithmetic."),
    ("3", FLAG_X, "Undocumented copy of result bit 3. As with flag 5, present but rarely useful."),
    ("P", FLAG_P, "Parity/Overflow — after logic ops, parity of the result; after arithmetic, signed overflow."),
    ("N", FLAG_N, "Add/Subtract — records whether the last op was a subtraction. Only DAA reads it."),
    ("C", FLAG_C, "Carry — carry out of bit 7, or a borrow. What JR C / JR NC test, and what rotates shift through."),
]


class _ClickableLabel(QLabel):
    """A QLabel that reports clicks -- registers are edited by clicking their cell."""

    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt naming)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


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
            for c, (label, attr, width) in enumerate(row):
                cell = _ClickableLabel()
                cell.setFont(monospace_font())
                cell.setText(f"{label:>3} ----")
                cell.setToolTip(f"Click to set {label}")
                cell.clicked.connect(
                    lambda name=label, a=attr, w=width: self._edit_register(name, a, w)
                )
                self._value_labels[attr] = cell
                grid.addWidget(cell, r, c)
        root.addLayout(grid)

        flags_row = QGridLayout()
        flags_row.setHorizontalSpacing(6)
        caption = QLabel("flags")
        caption.setStyleSheet("color: palette(mid);")
        flags_row.addWidget(caption, 0, 0)
        for i, (name, _mask, description) in enumerate(_FLAGS, start=1):
            f = QLabel(name)
            f.setAlignment(Qt.AlignCenter)
            f.setToolTip(description)
            f.setFont(monospace_font())
            f.setStyleSheet("border: 1px solid palette(mid); border-radius: 3px; padding: 1px 4px;")
            self._flag_labels[name] = f
            flags_row.addWidget(f, 0, i)
        flags_row.setColumnStretch(len(_FLAGS) + 1, 1)
        root.addLayout(flags_row)

        # T-state read-out. On a Spectrum, time *is* T-states: a frame is exactly 69888
        # of them (70908 on 128K), and where you are within that frame decides whether
        # the beam has drawn your line yet. "step" is the cost of whatever ran since the
        # last refresh -- while single-stepping that is precisely the instruction's cost,
        # which is the number you need when hand-timing a loop.
        self._tstates_label = QLabel()
        self._tstates_label.setFont(monospace_font())
        self._tstates_label.setStyleSheet("color: palette(mid);")
        root.addWidget(self._tstates_label)
        root.addStretch(1)

        self._previous_total = machine.cpu.t_states
        self.refresh()

    def refresh(self, frame_count: int | None = None) -> None:
        if not self.isVisible():
            return
        self._refresh_tstates()
        regs = self.machine.cpu.regs
        for row in _REG_ROWS:
            for label, attr, width in row:
                self._value_labels[attr].setText(f"{label:>3} {getattr(regs, attr):0{width}X}")
        for name, mask, _description in _FLAGS:
            on = bool(regs.f & mask)
            self._flag_labels[name].setStyleSheet(
                "border-radius: 3px; padding: 1px 4px;"
                + ("border: 1px solid palette(highlight); background: palette(highlight); color: palette(highlighted-text);"
                   if on else "border: 1px solid palette(mid); color: palette(mid);")
            )

    def set_register(self, attr: str, value: int, width: int) -> None:
        """Write a register, masked to its real width. Refreshes so the change is visible."""
        mask = (1 << (width * 4)) - 1
        setattr(self.machine.cpu.regs, attr, value & mask)
        self.refresh()

    def _edit_register(self, label: str, attr: str, width: int) -> None:
        """Prompt for a new value for a register.

        Editing registers is what turns the debugger from a microscope into a
        workbench: force a flag, retry a branch, skip a call by moving PC. It is only
        meaningful while paused -- writing a register under a running machine would be
        overwritten by the next instruction before you saw it.
        """
        current = getattr(self.machine.cpu.regs, attr)
        text, ok = QInputDialog.getText(
            self, f"Set {label}", f"{label} (hex):", text=f"{current:0{width}X}"
        )
        if not ok or not text.strip():
            return
        try:
            value = int(text.strip().lstrip("$#").removeprefix("0x"), 16)
        except ValueError:
            return
        self.set_register(attr, value, width)

    def _refresh_tstates(self) -> None:
        machine = self.machine
        total = machine.cpu.t_states
        step = total - self._previous_total
        self._previous_total = total
        within = machine.frame_t_state
        frame = machine.frame_tstates
        percent = 100.0 * within / frame if frame else 0.0
        self._tstates_label.setText(
            f"T  frame {within:5d}/{frame} ({percent:4.1f}%)   step +{step:<6d} total {total}"
        )

    def set_mono_scale(self, scale: float) -> None:
        font = monospace_font(scale)
        for label in (*self._value_labels.values(), *self._flag_labels.values(),
                      self._tstates_label):
            label.setFont(font)
