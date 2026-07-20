"""The central, multi-tab code/text editor (the dock anchor).

Each tab is a CodeEdit -- a QPlainTextEdit with the developer conveniences you'd
expect: Z80 syntax colouring, space-based indentation, a left gutter showing line
numbers and clickable breakpoint dots, and current-line highlighting. The
EditorArea manages the tabs, opens/saves files, and shows a dot on modified tabs.

Tabs are identified by the file path stored on each widget (not by index), so
reordering or closing tabs never confuses which file is which. Breakpoints are
kept per file as line numbers; wiring them to the debugger (line -> address) comes
with the debugger.
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPolygon, QTextCursor, QTextFormat, QTextOption
from PyQt5.QtWidgets import QPlainTextEdit, QTabWidget, QTextEdit, QWidget

from zxemu_ui.theme import monospace_font
from zxemu_ui.z80_highlighter import Z80Highlighter

_SPECIAL_CHARS = QTextOption.ShowTabsAndSpaces  # spaces/tabs only, no line marks
_GUTTER_BG = QColor("#2b2b2b")
_LINE_NUMBER = QColor("#6d7276")
_BREAKPOINT = QColor("#e5484d")
_CURRENT_LINE = QColor("#2a2a2a")
_EXEC_LINE = QColor("#4a3f1a")   # highlighted line where execution is paused
_EXEC_ARROW = QColor("#e0a13a")  # gutter arrow on the execution line
_BREAKPOINT_COLUMN = 18  # width of the clickable breakpoint strip, px

_WELCOME = (
    "; zxide\n"
    "; ----\n"
    "; Open a source file or text asset from the Project panel to edit it here.\n"
    "; Ctrl+B builds and runs the project.\n"
)


class _Gutter(QWidget):
    """The editor's left margin: line numbers + breakpoint dots. Painted by CodeEdit."""

    def __init__(self, editor: "CodeEdit"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self._editor.paint_gutter(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._editor.gutter_click(event.y())


class CodeEdit(QPlainTextEdit):
    """A code editor: space indent, line-number + breakpoint gutter, current-line."""

    INDENT_WIDTH = 4
    breakpoints_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._breakpoints: set[int] = set()  # 0-based block numbers
        self._exec_block: int | None = None  # 0-based line where execution is paused
        self._gutter = _Gutter(self)
        self.blockCountChanged.connect(lambda _n: self._update_gutter_width())
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._refresh_selections)
        self._update_gutter_width()
        self._refresh_selections()

    # --- indentation (spaces, not tabs) ---------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Tab and event.modifiers() == Qt.NoModifier:
            column = self.textCursor().positionInBlock()
            self.insertPlainText(" " * (self.INDENT_WIDTH - column % self.INDENT_WIDTH))
            return
        if event.key() == Qt.Key_Backtab:
            self._dedent()
            return
        super().keyPressEvent(event)

    def _dedent(self) -> None:
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.StartOfLine)
        leading = len(cursor.block().text()) - len(cursor.block().text().lstrip(" "))
        for _ in range(min(self.INDENT_WIDTH, leading)):
            cursor.deleteChar()
        cursor.endEditBlock()

    # --- breakpoints -----------------------------------------------------------

    def breakpoints(self) -> set[int]:
        """The breakpoint line numbers (1-based)."""
        return {block + 1 for block in self._breakpoints}

    def toggle_breakpoint(self, block: int) -> None:
        self._breakpoints.symmetric_difference_update({block})
        self._gutter.update()
        self.breakpoints_changed.emit()

    def gutter_click(self, y: int) -> None:
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        while block.isValid():
            bottom = top + self.blockBoundingRect(block).height()
            if top <= y <= bottom:
                self.toggle_breakpoint(block.blockNumber())
                return
            block = block.next()
            top = bottom

    # --- the gutter ------------------------------------------------------------

    def gutter_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return _BREAKPOINT_COLUMN + 10 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _on_update_request(self, rect, dy) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        area = self.contentsRect()
        self._gutter.setGeometry(area.left(), area.top(), self.gutter_width(), area.height())

    def paint_gutter(self, event) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), _GUTTER_BG)
        width = self.gutter_width()
        line_height = self.fontMetrics().height()

        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        while block.isValid() and top <= event.rect().bottom():
            bottom = top + self.blockBoundingRect(block).height()
            if block.isVisible() and bottom >= event.rect().top():
                center_y = int(top) + line_height // 2
                # Arrow (execution) on the left and breakpoint dot on the right are drawn
                # independently, so a breakpoint stays visible -- and removable -- even
                # while execution is stopped on that same line.
                if block.blockNumber() == self._exec_block:
                    painter.setBrush(_EXEC_ARROW)
                    painter.setPen(Qt.NoPen)
                    painter.drawPolygon(QPolygon([
                        QPoint(2, center_y - 4), QPoint(2, center_y + 4), QPoint(9, center_y),
                    ]))
                if block.blockNumber() in self._breakpoints:
                    painter.setBrush(_BREAKPOINT)
                    painter.setPen(Qt.NoPen)
                    radius = 4
                    painter.drawEllipse(13 - radius, center_y - radius, 2 * radius, 2 * radius)
                painter.setPen(_LINE_NUMBER)
                painter.drawText(
                    0, int(top), width - 6, line_height,
                    Qt.AlignRight | Qt.AlignVCenter, str(block.blockNumber() + 1),
                )
            block = block.next()
            top = bottom

    # --- line highlights (cursor line + execution line) ------------------------

    def set_execution_block(self, block: int | None) -> None:
        """Mark (or clear) the line where execution is currently paused."""
        self._exec_block = block
        self._refresh_selections()
        self._gutter.update()

    def _refresh_selections(self) -> None:
        selections = []
        cursor_line = QTextEdit.ExtraSelection()
        cursor_line.format.setBackground(_CURRENT_LINE)
        cursor_line.format.setProperty(QTextFormat.FullWidthSelection, True)
        cursor_line.cursor = self.textCursor()
        cursor_line.cursor.clearSelection()
        selections.append(cursor_line)

        if self._exec_block is not None:
            block = self.document().findBlockByNumber(self._exec_block)
            if block.isValid():
                exec_line = QTextEdit.ExtraSelection()
                exec_line.format.setBackground(_EXEC_LINE)
                exec_line.format.setProperty(QTextFormat.FullWidthSelection, True)
                exec_line.cursor = self.textCursor()
                exec_line.cursor.setPosition(block.position())
                exec_line.cursor.clearSelection()
                selections.append(exec_line)  # drawn on top of the cursor line
        self.setExtraSelections(selections)


class EditorArea(QTabWidget):
    """A tab group of code documents; the window's central editing surface."""

    breakpoints_changed = pyqtSignal()  # any tab's breakpoints changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDocumentMode(True)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.tabCloseRequested.connect(self.removeTab)
        self._scale = 1.0
        self._show_special = False
        self._add_welcome()

    def _add_welcome(self) -> None:
        edit = self._new_edit()
        edit.setPlainText(_WELCOME)
        edit.document().setModified(False)
        self.addTab(edit, "welcome")

    def _new_edit(self) -> CodeEdit:
        edit = CodeEdit()
        edit.setFont(monospace_font(self._scale))
        edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        edit.setTabStopDistance(4 * edit.fontMetrics().horizontalAdvance(" "))
        edit._highlighter = Z80Highlighter(edit.document())  # keep a reference alive
        edit.breakpoints_changed.connect(self.breakpoints_changed)  # bubble up
        self._apply_special_chars(edit)
        return edit

    # --- breakpoints & navigation ---------------------------------------------

    def all_breakpoints(self) -> dict[str, set[int]]:
        """Map each open file with breakpoints to its breakpoint line numbers."""
        result = {}
        for i in range(self.count()):
            widget = self.widget(i)
            path = widget.property("file_path") if widget else None
            if path and isinstance(widget, CodeEdit) and widget.breakpoints():
                result[path] = widget.breakpoints()
        return result

    def goto_line(self, path: str, line: int) -> None:
        """Open (or focus) a file and move the cursor to a 1-based line."""
        self.open_file(path)
        edit = self.currentWidget()
        if not isinstance(edit, QPlainTextEdit):
            return
        block = edit.document().findBlockByNumber(max(0, line - 1))
        cursor = edit.textCursor()
        cursor.setPosition(block.position())
        edit.setTextCursor(cursor)
        edit.centerCursor()

    def set_execution_line(self, path: str, line: int) -> None:
        """Highlight the paused-execution line: open the file, mark it, scroll to it."""
        self.open_file(path)
        target = self.currentWidget()
        for i in range(self.count()):
            widget = self.widget(i)
            if isinstance(widget, CodeEdit):
                widget.set_execution_block(line - 1 if widget is target else None)
        self.goto_line(path, line)

    def clear_execution_line(self) -> None:
        for i in range(self.count()):
            widget = self.widget(i)
            if isinstance(widget, CodeEdit):
                widget.set_execution_block(None)

    # --- opening / saving ------------------------------------------------------

    def open_file(self, path: str) -> None:
        """Open a text file in a tab (or focus it if already open)."""
        key = str(Path(path).resolve())
        existing = self._index_of_path(key)
        if existing is not None:
            self.setCurrentIndex(existing)
            return
        edit = self._new_edit()
        edit.setPlainText(Path(path).read_text(encoding="utf-8", errors="replace"))
        edit.setProperty("file_path", key)  # the tab's identity, stable across reorders
        edit.document().setModified(False)
        edit.document().modificationChanged.connect(lambda _m, e=edit: self._update_title(e))
        index = self.addTab(edit, Path(path).name)
        self.setCurrentIndex(index)

    def save_current(self) -> None:
        self._save(self.currentWidget())

    def save_all(self) -> None:
        for i in range(self.count()):
            self._save(self.widget(i))

    def _save(self, edit) -> None:
        if not isinstance(edit, QPlainTextEdit):
            return
        path = edit.property("file_path")
        if not path or not edit.document().isModified():
            return  # nothing to save (welcome tab, or unchanged)
        Path(path).write_text(edit.toPlainText(), encoding="utf-8")
        edit.document().setModified(False)

    def _update_title(self, edit) -> None:
        index = self.indexOf(edit)
        if index < 0:
            return
        name = Path(edit.property("file_path") or "untitled").name
        self.setTabText(index, f"● {name}" if edit.document().isModified() else name)

    def _index_of_path(self, key: str) -> int | None:
        for i in range(self.count()):
            widget = self.widget(i)
            if widget is not None and widget.property("file_path") == key:
                return i
        return None

    # --- appearance ------------------------------------------------------------

    def set_mono_scale(self, scale: float) -> None:
        self._scale = scale
        for i in range(self.count()):
            widget = self.widget(i)
            if isinstance(widget, QPlainTextEdit):
                widget.setFont(monospace_font(scale))

    def set_show_special(self, on: bool) -> None:
        self._show_special = on
        for i in range(self.count()):
            widget = self.widget(i)
            if isinstance(widget, QPlainTextEdit):
                self._apply_special_chars(widget)

    def _apply_special_chars(self, edit: QPlainTextEdit) -> None:
        option = edit.document().defaultTextOption()
        flags = option.flags()
        option.setFlags(flags | _SPECIAL_CHARS if self._show_special else flags & ~_SPECIAL_CHARS)
        edit.document().setDefaultTextOption(option)
