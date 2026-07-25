"""The Output panel: the build/log console, with clickable result lines.

Two things beyond a plain read-only text box:

**Linked lines.** A search result is only useful if it takes you there. Rather than
parsing the console's text back into a path and a line number (which breaks the moment a
filename contains a colon, or a log line happens to look like a result), each linked line
*records* its target when it is appended: ``_targets`` maps a document block number to
the (path, line) it stands for. Clicking a line looks it up; lines with no entry are inert
log text and behave exactly as before.

**Clear, on the right-click menu.** A console that only grows is unreadable by the third
build, but clearing it is a once-in-a-while action and a permanent button costs a row of
height in a panel whose whole job is showing as many lines as possible. So it joins the
context menu the text box already has (Copy, Select All), where the other things you
occasionally do to a log already live. Clearing empties the text and the link map
together -- keeping stale targets would leave clicks jumping to results that are no longer
on screen.
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QTextCharFormat
from PyQt5.QtWidgets import QPlainTextEdit, QWidget

from zxemu_ui.theme import monospace_font


class OutputConsole(QPlainTextEdit):
    """Read-only log where some lines are links to a file and line number."""

    link_activated = pyqtSignal(str, int)  # (file path, 1-based line)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("Build output and search results will appear here.")
        self.setFont(monospace_font())  # column-aligned, like a code editor
        self.setMouseTracking(True)     # so the cursor can change over a link
        self._targets: dict[int, tuple[str, int]] = {}

    # --- appending -------------------------------------------------------------

    def append_line(self, message: str) -> None:
        """Append plain log text (no link)."""
        self.appendPlainText(message)

    def append_link(self, message: str, path: str | Path, line: int) -> None:
        """Append a line that jumps to ``path`` at ``line`` when clicked."""
        self.appendPlainText(message)
        block = self.document().blockCount() - 1
        self._targets[block] = (str(path), line)
        self._underline(block)

    def clear_output(self) -> None:
        """Empty the console *and* forget every link target."""
        self.clear()
        self._targets.clear()

    def set_mono_scale(self, scale: float) -> None:
        self.setFont(monospace_font(scale))

    def _underline(self, block_number: int) -> None:
        """Underline a linked line so it reads as clickable, not as more log text."""
        block = self.document().findBlockByNumber(block_number)
        if not block.isValid():
            return
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        cursor.setPosition(block.position() + block.length() - 1, cursor.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setFontUnderline(True)
        cursor.mergeCharFormat(fmt)

    # --- interaction -----------------------------------------------------------

    def target_at(self, position) -> tuple[str, int] | None:
        """The link under a viewport position, or None."""
        return self._targets.get(self.cursorForPosition(position).blockNumber())

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """A left click on a linked line follows it; anything else selects text."""
        if event.button() == Qt.LeftButton:
            target = self.target_at(event.pos())
            if target is not None:
                self.link_activated.emit(*target)
                return  # don't also move the caret -- the click was navigation
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Show a hand over links, so it's discoverable that they can be clicked."""
        over_link = self.target_at(event.pos()) is not None
        self.viewport().setCursor(Qt.PointingHandCursor if over_link else Qt.IBeamCursor)
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """The text box's own menu (Copy, Select All...) plus Clear."""
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        clear = menu.addAction("Clear")
        clear.setEnabled(bool(self.toPlainText()))  # nothing to clear in an empty console
        clear.triggered.connect(self.clear_output)
        menu.exec_(event.globalPos())
        menu.deleteLater()
