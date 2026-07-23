"""AnalysisView -- the panel that answers questions *about* the program.

Every other debug panel shows the machine's current state: these registers, these
bytes, this instruction. This one shows conclusions drawn across the whole address
space -- where a byte sequence occurs, what refers to an address, which code has
actually run, what ran just before things went wrong.

They share a panel because they share a shape: you ask a question, you get a list of
addresses, and the useful next move is always the same -- go look at one in the
disassembly. So results are plain ``$xxxx`` lines, and the view emits
:attr:`address_activated` when you double-click one, which MainWindow wires to the
disassembly panel.

The analysis itself lives in :mod:`zxemu_core.debug.analysis` (no Qt, independently
testable); this file is only presentation.

A word on trust
---------------
The results here are not all equally certain, and the panel says so in its headings
rather than letting you assume:

  * **Search** is exact -- those bytes are there.
  * **Cross-references** are a static scan: it finds instructions whose operand
    matches, including inside data that merely looks like code, and it cannot see
    computed destinations (``JP (HL)``, jump tables) at all.
  * **Coverage** never lies about what executed, but only knows what has executed
    *so far*. An unmarked address means "not yet", never "never".
"""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from zxemu_core.debug import analysis, rom_symbols
from zxemu_ui.theme import monospace_font

MAX_RESULTS = 500  # a search that matches thousands of addresses is a question, not an answer


class AnalysisView(QWidget):
    """Shows search hits, cross-references, coverage and trace as address listings."""

    address_activated = pyqtSignal(int)  # double-clicked an address in the results

    def __init__(self, machine, parent=None):
        super().__init__(parent)
        self.machine = machine

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._output.setFont(monospace_font())
        self._output.mouseDoubleClickEvent = self._on_double_click
        root.addWidget(self._output, 1)

        self._show(["Reversing ▸ pick a query from the menu."])

    # --- presentation ----------------------------------------------------------

    def _show(self, lines) -> None:
        self._output.setPlainText("\n".join(lines))

    def _describe(self, address: int) -> str:
        """An address plus whatever name we can put to it, ROM or otherwise."""
        name = rom_symbols.name_for(address) if self.machine.rom_symbols_valid() else None
        if name is None:
            inside = rom_symbols.enclosing(address) if self.machine.rom_symbols_valid() else None
            if inside is not None:
                name = f"{inside[0]}+${inside[1]:02X}"
        return f"  ${address:04X}" + (f"   {name}" if name else "")

    def _on_double_click(self, event) -> None:
        """Double-clicking a result line jumps the disassembly there."""
        cursor = self._output.cursorForPosition(event.pos())
        text = cursor.block().text().strip()
        if text.startswith("$"):
            try:
                self.address_activated.emit(int(text[1:5], 16))
            except ValueError:
                pass

    @staticmethod
    def _truncated(hits) -> tuple[list, str]:
        if len(hits) <= MAX_RESULTS:
            return hits, ""
        return hits[:MAX_RESULTS], f"  … and {len(hits) - MAX_RESULTS} more (showing {MAX_RESULTS})"

    # --- queries ---------------------------------------------------------------

    def find_bytes(self, pattern: bytes, description: str) -> None:
        hits = analysis.search_bytes(self.machine.memory, pattern)
        shown, note = self._truncated(hits)
        header = f"Search for {description} — {len(hits)} match(es). Exact: these bytes are there."
        self._show([header, ""] + [self._describe(a) for a in shown] + ([note] if note else []))

    def find_text(self, text: str) -> None:
        self.find_bytes(text.encode("ascii", "ignore"), f'text "{text}"')

    def cross_references(self, target: int) -> None:
        references = analysis.cross_references(self.machine.memory, target)
        shown, note = self._truncated(references)
        lines = [
            f"References to ${target & 0xFFFF:04X} — {len(references)} found.",
            "Static scan: may match data that looks like code, and cannot see",
            "computed destinations (JP (HL), jump tables, self-modified operands).",
            "",
        ]
        for reference in shown:
            lines.append(f"{self._describe(reference.address)}   {reference.kind}")
        self._show(lines + ([note] if note else []))

    def show_coverage(self, coverage) -> None:
        executed = coverage.count()
        runs = coverage.ranges(minimum_length=2)
        shown, note = self._truncated(runs)
        lines = [
            f"Coverage — {executed} addresses executed, in {len(runs)} run(s).",
            "Unmarked means 'not executed yet', never 'unreachable'.",
            "",
        ]
        for start, end in shown:
            lines.append(f"  ${start:04X}-${end - 1:04X}   {end - start} bytes")
        if not runs:
            lines.append("  (nothing recorded — switch on Reversing ▸ Record Coverage and run)")
        self._show(lines + ([note] if note else []))

    def show_trace(self, entries) -> None:
        lines = [
            f"Execution trace — last {len(entries)} instruction(s), oldest first.",
            "",
        ]
        for address, sp in entries[-MAX_RESULTS:]:
            lines.append(f"{self._describe(address)}   sp=${sp:04X}")
        if not entries:
            lines.append("  (nothing recorded — switch on Reversing ▸ Record Trace and run)")
        self._show(lines)

    def set_mono_scale(self, scale: float) -> None:
        self._output.setFont(monospace_font(scale))
