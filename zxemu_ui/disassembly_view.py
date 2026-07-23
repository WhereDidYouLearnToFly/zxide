"""DisassemblyView -- live disassembly of the code around the program counter.

The debugger's third view of the same memory. Registers say *what the CPU holds*,
the hex dump says *what the bytes are*, and this says *what those bytes mean* --
decoding them back into Z80 mnemonics through :mod:`zxemu_core.disassembler`.

It is the view you actually single-step in: with "Follow PC" on it re-centres on the
program counter after every step, so F11/F10/Shift+F11 walk down the listing.

A note on starting address
--------------------------
Z80 instructions are variable length and there is no way to find an instruction
boundary by looking backwards -- the same byte can be an opcode or an operand
depending on where you started reading. So a disassembly is only trustworthy if it
begins on a real boundary. Following PC always is (the CPU is about to execute
there); typing an arbitrary address may not be, and the listing will resynchronise
by luck after a few instructions. That is inherent to the architecture, not a bug
here, which is why Follow PC is the default.
"""

from __future__ import annotations

from PyQt5.QtCore import QRegExp
from PyQt5.QtGui import QRegExpValidator
from PyQt5.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from zxemu_core import disassembler, rom_symbols
from zxemu_ui.theme import monospace_font

INSTRUCTION_COUNT = 24  # how many instructions to decode per refresh
_MAX_OPCODE_BYTES = 4   # longest Z80 instruction, for column alignment


class DisassemblyView(QWidget):
    """Disassembles a window of instructions, refreshed each frame."""

    def __init__(self, machine, parent=None):
        super().__init__(parent)
        self.machine = machine
        self._base = 0x0000
        # Labels from the last build's SLD, so your own code disassembles with your own
        # names. Set by MainWindow after each build; None until then.
        self.source_map = None

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
        self._follow_pc.setChecked(True)  # see the module docstring: the only address
        self._follow_pc.toggled.connect(lambda _on: self.refresh(force=True))
        bar.addWidget(self._follow_pc)
        bar.addStretch(1)
        root.addLayout(bar)

        self._listing = QPlainTextEdit()
        self._listing.setReadOnly(True)
        self._listing.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._listing.setFont(monospace_font())
        root.addWidget(self._listing, 1)

        self.refresh(force=True)

    # --- navigation ------------------------------------------------------------

    def goto(self, address: int) -> None:
        """Show the listing from ``address``, releasing Follow PC so it stays there."""
        self._base = address & 0xFFFF
        self._follow_pc.setChecked(False)
        self._addr_edit.setText(f"{self._base:04X}")
        self.refresh(force=True)

    def goto_pc(self) -> None:
        """Re-centre on the program counter and keep following it."""
        self._follow_pc.setChecked(True)
        self.refresh(force=True)

    @property
    def following_pc(self) -> bool:
        return self._follow_pc.isChecked()

    def set_following_pc(self, on: bool) -> None:
        self._follow_pc.setChecked(bool(on))

    # --- rendering -------------------------------------------------------------

    def _on_addr_edited(self) -> None:
        text = self._addr_edit.text().strip()
        if text:
            self.goto(int(text, 16))

    def refresh(self, frame_count: int | None = None, force: bool = False) -> None:
        if not force and not self.isVisible():
            return
        pc = self.machine.cpu.regs.pc
        base = pc if self._follow_pc.isChecked() else self._base
        if self._follow_pc.isChecked():
            self._addr_edit.setText(f"{base:04X}")

        # ROM routine names are only meaningful when the 48-BASIC ROM is the one paged
        # in; on a 128K showing ROM 0 they would label the wrong code (see rom_symbols).
        label_roms = self.machine.rom_symbols_valid()

        lines = []
        inside = rom_symbols.enclosing(pc) if label_roms else None
        if inside is not None:
            lines.append(f"; in {inside[0]}+${inside[1]:02X}")
        for address, raw, text in disassembler.disassemble(
            self.machine.memory, base, INSTRUCTION_COUNT
        ):
            marker = ">" if address == pc else " "
            hex_bytes = " ".join(f"{b:02X}" for b in raw)
            name = rom_symbols.name_for(address) if label_roms else None
            if name is None and self.source_map is not None:
                name = self.source_map.label_for(address)  # your own labels
            if name is not None:
                lines.append(f" {name}:")
            text = rom_symbols.annotate(text, label_roms)
            lines.append(f"{marker}{address:04X}  {hex_bytes:<{_MAX_OPCODE_BYTES * 3}} {text}")
        self._listing.setPlainText("\n".join(lines))

    def set_mono_scale(self, scale: float) -> None:
        self._listing.setFont(monospace_font(scale))
