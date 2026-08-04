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

from PyQt5.QtCore import QEvent, QPoint, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPolygon, QStandardItem, QStandardItemModel, QTextCursor, QTextDocument, QTextFormat, QTextOption
from PyQt5.QtWidgets import QAction, QCompleter, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QTabWidget, QTextEdit, QToolButton, QToolTip, QWidget

from zxemu_core.debug import asm_defs, asm_help, asm_symbols
from zxemu_core.debug.asm_hidden import SUSPECTS
from zxemu_ui.theme import monospace_font
from zxemu_ui.z80_highlighter import Z80Highlighter

_SPECIAL_CHARS = QTextOption.ShowTabsAndSpaces  # spaces/tabs only, no line marks
_GUTTER_BG = QColor("#2b2b2b")
_LINE_NUMBER = QColor("#6d7276")
_BREAKPOINT = QColor("#e5484d")
_CURRENT_LINE = QColor("#2a2a2a")
_EXEC_LINE = QColor("#4a3f1a")   # highlighted line where execution is paused
_MATCH = QColor("#3d5a80")       # every occurrence of what Ctrl+F is looking for

#: How many characters before the completion popup appears on its own. Two, because one
#: matches most of a project and would pop up constantly; Ctrl+Space forces it any time.
COMPLETE_AFTER = 2

#: Enough to see a label's uses down a file; a cap so a one-character query in a 2000-line
#: source doesn't build tens of thousands of selections on every keystroke.
_MAX_HIGHLIGHTS = 500
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
    #: A name was right-clicked; the window resolves it (this widget knows no project).
    definition_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._breakpoints: set[int] = set()  # 0-based block numbers
        self._exec_block: int | None = None  # 0-based line where execution is paused
        self._instruction_help = True  # hover tooltips; switched off in Settings
        self._symbols: dict[str, asm_symbols.Constant] = {}  # equ constants, rebuilt on demand
        self._symbols_revision = -1  # document revision the table above was built from
        self._read_source = None     # supplied by EditorArea; reads other files' text
        self._search, self._search_cased = "", False  # what Ctrl+F is highlighting
        self._gutter = _Gutter(self)
        self._make_completer()
        self.blockCountChanged.connect(lambda _n: self._update_gutter_width())
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._refresh_selections)
        self._update_gutter_width()
        self._refresh_selections()

    # --- instruction help ------------------------------------------------------

    def event(self, event):  # noqa: N802
        """Hover an instruction to see what it does and what it costs.

        Handled here rather than through ``setToolTip`` because the text depends on where
        the pointer is, not on the widget: every line has a different answer, and most
        lines have none.

        The whole line is looked up, not the word under the pointer, so hovering the
        ``(hl)`` in ``ld a,(hl)`` answers the same question as hovering the ``ld`` --
        being precise about which token you touched would only feel broken.
        """
        if event.type() == QEvent.ToolTip:
            if not self._instruction_help:
                QToolTip.hideText()
                return True
            cursor = self.cursorForPosition(self.viewport().mapFrom(self, event.pos()))
            help_text = asm_help.describe(cursor.block().text(), cursor.positionInBlock(), self.symbol_table())
            if help_text is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(event.globalPos(), help_text.as_text(), self)
            return True
        return super().event(event)

    def insertFromMimeData(self, source) -> None:  # noqa: N802
        """Paste plain text, and only plain text.

        Assembly source has no use for a non-breaking space, a zero-width space or a
        text-direction mark -- but a browser, a PDF and most chat clients hand them out
        freely, and they arrive looking exactly like what you meant to paste. Cleaning at
        the door is better than detecting them later: the alternative is an assembler
        error naming a character nobody can see, which is precisely the hour this cost.

        A non-breaking space becomes an ordinary space (that is what it was standing in
        for); everything else invisible is simply dropped.
        """
        text = source.text()
        if text:
            cleaned = "".join(" " if ch == " " else "" if ch in SUSPECTS else ch for ch in text)
            if cleaned != text:
                self.insertPlainText(cleaned)
                return
        super().insertFromMimeData(source)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        """The standard menu, with Go to Definition on top when a name was clicked.

        Built from ``createStandardContextMenu`` rather than replacing it: undo, cut, paste
        and select-all are what a right-click means everywhere, and losing them to gain one
        entry would be a poor trade. The name comes from *where you clicked*, not from the
        caret -- right-clicking a label across the file should ask about that label, not
        about wherever you happened to be typing.
        """
        menu = self.createStandardContextMenu()
        cursor = self.cursorForPosition(event.pos())
        name = asm_defs.name_at(cursor.block().text(), cursor.positionInBlock())
        if name:
            action = QAction("Go to Definition of “{}”".format(name), menu)
            action.setShortcut("F12")
            action.triggered.connect(lambda _checked=False, n=name: self.definition_requested.emit(n))
            first = menu.actions()[0] if menu.actions() else None
            menu.insertAction(first, action)
            menu.insertSeparator(first)
        if any(ch in SUSPECTS for ch in self.toPlainText()):
            menu.addSeparator()
            clean = QAction("Remove invisible characters from this file", menu)
            clean.triggered.connect(self.remove_invisible)
            menu.addAction(clean)
        menu.exec_(event.globalPos())

    def remove_invisible(self) -> int:
        """Strip every invisible character from this document. Returns how many went.

        One undo step, and it goes through the document rather than the file, so it is
        taken back the same way as any other edit.
        """
        text = self.toPlainText()
        cleaned = "".join(" " if ch == " " else "" if ch in SUSPECTS else ch for ch in text)
        if cleaned == text:
            return 0
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)
        cursor.insertText(cleaned)
        cursor.endEditBlock()
        return sum(1 for ch in text if ch in SUSPECTS)

    # --- completion -------------------------------------------------------------

    def set_completions(self, entries: list) -> None:
        """Supply ``[(name, detail), ...]`` -- the project's labels, constants and macros.

        Pushed in rather than gathered here: the names come from the whole include tree,
        which only the window knows how to walk, and rebuilding that per keystroke would
        be the one thing an editor must never do.
        """
        model = QStandardItemModel(self)
        for name, detail in entries:
            item = QStandardItem(name)
            item.setToolTip(detail)
            model.appendRow(item)
        self._completer.setModel(model)

    def _make_completer(self) -> None:
        self._completer = QCompleter(self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.activated.connect(self._insert_completion)
        self._completer.setModel(QStandardItemModel(self))

    def _prefix_under_cursor(self) -> str:
        """The identifier being typed, back to whatever is not part of a name."""
        text = self.textCursor().block().text()
        column = self.textCursor().positionInBlock()
        start = column
        while start > 0 and (text[start - 1].isalnum() or text[start - 1] in "_@."):
            start -= 1
        return text[start:column]

    def _insert_completion(self, completion: str) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, len(self._prefix_under_cursor()))
        cursor.insertText(completion)
        self.setTextCursor(cursor)

    def _update_completer(self, forced: bool = False) -> None:
        """Show, filter or hide the popup for what is being typed right now."""
        prefix = self._prefix_under_cursor()
        if not forced and len(prefix) < COMPLETE_AFTER:
            self._completer.popup().hide()
            return
        self._completer.setCompletionPrefix(prefix)
        if self._completer.completionCount() == 0:
            self._completer.popup().hide()
            return
        self._completer.popup().setCurrentIndex(self._completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(self._completer.popup().sizeHintForColumn(0) + self._completer.popup().verticalScrollBar().sizeHint().width() + 24)
        self._completer.complete(rect)

    def set_instruction_help(self, on: bool) -> None:
        self._instruction_help = on

    def set_source_reader(self, reader) -> None:
        """Tell this tab how to read the files it includes (EditorArea supplies it)."""
        self._read_source = reader

    def symbol_table(self) -> dict[str, asm_symbols.Constant]:
        """The ``equ`` constants this file can see, scanned at most once per edit.

        Rebuilt lazily on hover rather than on every keystroke: the scan is cheap, but
        typing is the one thing in an editor that must never wait, and nothing looks at
        this table until a tooltip is actually asked for.
        """
        revision = self.document().revision()
        if revision != self._symbols_revision:
            path = self.property("file_path")
            base = Path(path).parent if path else None
            self._symbols = asm_symbols.collect(self.toPlainText(), base, self._read_source)
            self._symbols_revision = revision
        return self._symbols

    def invalidate_symbols(self) -> None:
        """Forget the cached constants -- an included file changed underneath us."""
        self._symbols_revision = -1

    # --- indentation (spaces, not tabs) ---------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # While the completion popup is up it owns the navigation keys -- otherwise Enter
        # would insert a newline behind it and Up/Down would move the caret out from under
        # the list you are choosing from.
        if self._completer.popup().isVisible() and event.key() in (
            Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab, Qt.Key_Escape, Qt.Key_Up, Qt.Key_Down
        ):
            event.ignore()
            return
        if event.key() == Qt.Key_Space and event.modifiers() & Qt.ControlModifier:
            self._update_completer(forced=True)
            return
        if event.key() == Qt.Key_Tab and event.modifiers() == Qt.NoModifier:
            if self._shift_selected_lines(+1):
                return
            column = self.textCursor().positionInBlock()
            self.insertPlainText(" " * (self.INDENT_WIDTH - column % self.INDENT_WIDTH))
            return
        if event.key() == Qt.Key_Backtab:
            if self._shift_selected_lines(-1):
                return
            self._dedent()
            return
        super().keyPressEvent(event)
        self._update_completer()

    def _shift_selected_lines(self, direction: int) -> bool:
        """Indent (+1) or outdent (-1) every line of a multi-line selection.

        Returns False when the selection isn't a block of lines, so the caller falls back
        to the single-caret behaviour: with one line marked, Tab means "replace what I
        selected", which is what every editor does and what you want when retyping a
        token. It only becomes "move this code across" once more than one line is in play.

        The selection is re-made over the whole of those lines afterwards, so Tab can be
        pressed repeatedly to keep shifting the same block -- a selection that shrank to
        the changed text would be a one-shot.
        """
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return False
        document = self.document()
        first = document.findBlock(cursor.selectionStart()).blockNumber()
        end_block = document.findBlock(cursor.selectionEnd())
        last = end_block.blockNumber()
        # A drag that ends exactly at the start of a line took none of its text, so that
        # line is not part of what you selected and must not move with it.
        if last > first and end_block.position() == cursor.selectionEnd():
            last -= 1
        if first == last:
            return False

        editor = QTextCursor(document)
        editor.beginEditBlock()
        for number in range(first, last + 1):
            block = document.findBlockByNumber(number)
            text = block.text()
            editor.setPosition(block.position())
            if direction > 0:
                if text.strip():  # indenting a blank line would only leave trailing spaces
                    editor.insertText(" " * self.INDENT_WIDTH)
            elif text.startswith("\t"):  # a file written elsewhere may well use real tabs
                editor.deleteChar()
            else:
                for _ in range(min(self.INDENT_WIDTH, len(text) - len(text.lstrip(" ")))):
                    editor.deleteChar()
        editor.endEditBlock()

        start = document.findBlockByNumber(first)
        end = document.findBlockByNumber(last)
        reselected = QTextCursor(document)
        reselected.setPosition(start.position())
        reselected.setPosition(end.position() + end.length() - 1, QTextCursor.KeepAnchor)
        self.setTextCursor(reselected)
        return True

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

    # --- find in this document --------------------------------------------------

    def set_search(self, query: str, case_sensitive: bool = False) -> int:
        """Highlight every occurrence of ``query``. Returns how many there are.

        Highlighting *all* of them rather than only the one you are on: in assembly the
        useful question is usually "how many places use this label", and seeing four marks
        down the scrollbar's worth of text answers it without pressing next four times.
        """
        self._search, self._search_cased = query, case_sensitive
        self._refresh_selections()
        return len(self._match_positions())

    def _match_positions(self) -> list:
        """Every match as ``(start, end)``, capped so a one-letter query can't stall the UI."""
        if not self._search:
            return []
        flags = QTextDocument.FindCaseSensitively if self._search_cased else QTextDocument.FindFlags()
        found, cursor = [], QTextCursor(self.document())
        while len(found) < _MAX_HIGHLIGHTS:
            cursor = self.document().find(self._search, cursor, flags)
            if cursor.isNull():
                break
            found.append((cursor.selectionStart(), cursor.selectionEnd()))
        return found

    def find_next(self, forward: bool = True) -> tuple:
        """Move to the next (or previous) match, wrapping. Returns ``(which, total)``, 1-based."""
        matches = self._match_positions()
        if not matches:
            return 0, 0
        here = self.textCursor().selectionStart() if forward else self.textCursor().selectionStart()
        if forward:
            index = next((i for i, (start, _end) in enumerate(matches) if start > here), 0)
        else:
            earlier = [i for i, (start, _end) in enumerate(matches) if start < here]
            index = earlier[-1] if earlier else len(matches) - 1
        start, end = matches[index]
        cursor = self.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)
        self.centerCursor()
        return index + 1, len(matches)

    def _refresh_selections(self) -> None:
        selections = []
        cursor_line = QTextEdit.ExtraSelection()
        cursor_line.format.setBackground(_CURRENT_LINE)
        cursor_line.format.setProperty(QTextFormat.FullWidthSelection, True)
        cursor_line.cursor = self.textCursor()
        cursor_line.cursor.clearSelection()
        selections.append(cursor_line)

        # Match highlights sit above the current-line band and below the execution line:
        # you need to see a match on the line you are standing on, but never in place of
        # where the program is paused.
        for start, end in self._match_positions():
            match = QTextEdit.ExtraSelection()
            match.format.setBackground(_MATCH)
            match.cursor = QTextCursor(self.document())
            match.cursor.setPosition(start)
            match.cursor.setPosition(end, QTextCursor.KeepAnchor)
            selections.append(match)

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


class FindBar(QWidget):
    """The Ctrl+F strip: find as you type, in the file you are looking at.

    A bar under the editor rather than a dialog, for the reason every editor settled on
    one: a dialog covers the text you are searching and has to be dismissed before you can
    read the result. This stays out of the way, keeps the query while you move around, and
    Esc puts you back in the code.

    It is deliberately the *narrow* half of search. "Where is this label used" is a
    project-wide question and has its own answer (Ctrl+Shift+F, results in Output); this
    one is "take me to the next one of these in this file", which wants to be instant and
    to leave no trace.
    """

    #: ``(query, case sensitive)`` -- emitted as you type, so highlights follow the query.
    search_changed = pyqtSignal(str, bool)
    #: True for next, False for previous.
    step = pyqtSignal(bool)
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._field = QLineEdit()
        self._field.setPlaceholderText("Find in this file")
        self._field.setClearButtonEnabled(True)
        self._field.textChanged.connect(self._announce)
        self._field.returnPressed.connect(lambda: self.step.emit(True))

        self._cased = QToolButton()
        self._cased.setText("Aa")
        self._cased.setCheckable(True)
        self._cased.setToolTip("Match case")
        self._cased.toggled.connect(self._announce)

        self._count = QLabel("")
        self._count.setStyleSheet("color: #9aa0a6;")
        self._count.setMinimumWidth(90)

        previous, following, close = QToolButton(), QToolButton(), QToolButton()
        previous.setText("▲")
        previous.setToolTip("Previous match (Shift+F3)")
        previous.clicked.connect(lambda: self.step.emit(False))
        following.setText("▼")
        following.setToolTip("Next match (F3)")
        following.clicked.connect(lambda: self.step.emit(True))
        close.setText("✕")
        close.setToolTip("Close (Esc)")
        close.clicked.connect(self.closed)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(4)
        row.addWidget(QLabel("Find:"))
        row.addWidget(self._field, 1)
        for widget in (self._cased, previous, following, self._count, close):
            row.addWidget(widget)

    def _announce(self) -> None:
        self.search_changed.emit(self._field.text(), self._cased.isChecked())

    def query(self) -> str:
        return self._field.text()

    def case_sensitive(self) -> bool:
        return self._cased.isChecked()

    def start(self, seed: str = "") -> None:
        """Show the bar, pre-filled with ``seed`` (the selection, normally), and focus it."""
        if seed:
            self._field.setText(seed)
        self.show()
        self._field.setFocus()
        self._field.selectAll()
        self._announce()

    def show_count(self, which: int, total: int) -> None:
        if not self._field.text():
            self._count.setText("")
        elif not total:
            self._count.setText("no matches")
        else:
            self._count.setText("{} of {}".format(which or 1, total))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.closed.emit()
            return
        super().keyPressEvent(event)


class EditorArea(QTabWidget):
    """A tab group of code documents; the window's central editing surface."""

    #: Bubbled up from whichever tab was right-clicked.
    definition_requested = pyqtSignal(str)

    breakpoints_changed = pyqtSignal()  # any tab's breakpoints changed
    # Any edit, cursor move, or selection change in any tab. One signal rather than three
    # because everything downstream (currently the assembly meter) wants "the text or what
    # is selected in it is now different" and would otherwise connect to all three itself.
    cursor_or_text_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDocumentMode(True)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.tabCloseRequested.connect(self.removeTab)
        self._scale = 1.0
        self._show_special = False
        self._instruction_help = True
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
        edit.definition_requested.connect(self.definition_requested)
        edit.set_completions(getattr(self, "_completions", []))
        edit.textChanged.connect(self.cursor_or_text_changed)
        edit.cursorPositionChanged.connect(self.cursor_or_text_changed)
        edit.selectionChanged.connect(self.cursor_or_text_changed)
        edit.set_instruction_help(self._instruction_help)
        edit.set_source_reader(self._read_source_text)
        self._apply_special_chars(edit)
        return edit

    # --- find in the current document -------------------------------------------

    def selected_text(self) -> str:
        """What is selected in the current tab, if it is one line of it -- the Ctrl+F seed."""
        edit = self.currentWidget()
        if not isinstance(edit, QPlainTextEdit):
            return ""
        text = edit.textCursor().selectedText()
        return text if text and " " not in text else ""  # U+2029 is Qt's line separator

    def set_completions(self, entries: list) -> None:
        """Give every tab the project's names, and remember them for tabs opened later."""
        self._completions = entries
        for i in range(self.count()):
            widget = self.widget(i)
            if isinstance(widget, CodeEdit):
                widget.set_completions(entries)

    def set_search(self, query: str, case_sensitive: bool = False) -> int:
        """Highlight ``query`` in the current tab; returns the number of matches."""
        edit = self.currentWidget()
        return edit.set_search(query, case_sensitive) if isinstance(edit, CodeEdit) else 0

    def find_next(self, forward: bool = True) -> tuple:
        edit = self.currentWidget()
        return edit.find_next(forward) if isinstance(edit, CodeEdit) else (0, 0)

    def clear_search(self) -> None:
        """Drop the highlights everywhere, not just in the tab you happen to be on."""
        for i in range(self.count()):
            widget = self.widget(i)
            if isinstance(widget, CodeEdit):
                widget.set_search("")

    def name_at_cursor(self) -> str:
        """The identifier the caret is in, for Go to Definition."""
        edit = self.currentWidget()
        if not isinstance(edit, QPlainTextEdit):
            return ""
        cursor = edit.textCursor()
        if cursor.hasSelection():
            return cursor.selectedText().strip()
        return asm_defs.name_at(cursor.block().text(), cursor.positionInBlock())

    def source_reader(self):
        """The "path -> text" callable other panels should scan a project with.

        Handed out rather than each caller reading files itself, because only the editor
        knows about unsaved tabs -- and a memory map drawn from the saved copy of a file
        you are editing is showing you the past.
        """
        return self._read_source_text

    def _read_source_text(self, path: str) -> str | None:
        """The text of an included file: the open tab's copy if there is one, else disk.

        An include you are editing in another tab has to answer with what is on screen --
        reading the saved file would show a constant's old value moments after you changed
        it, which is worse than showing none.
        """
        wanted = str(path).lower()  # tabs are keyed by resolved path; Windows varies the case
        for i in range(self.count()):
            widget = self.widget(i)
            file_path = widget.property("file_path") if widget else None
            if file_path and str(file_path).lower() == wanted and isinstance(widget, QPlainTextEdit):
                return widget.toPlainText()
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def selected_or_all_text(self) -> tuple[str, bool]:
        """``(text, is_selection)`` -- what the caret has selected, or the whole document.

        "Whole file when nothing is selected" is the behaviour the assembly meter wants,
        and getting the text is the part that needs to know about Qt: ``selectedText()``
        joins lines with U+2029 rather than a newline, which any line-based consumer has
        to undo.
        """
        edit = self.currentWidget()
        if not isinstance(edit, QPlainTextEdit):
            return "", False
        cursor = edit.textCursor()
        if cursor.hasSelection():
            return cursor.selectedText().replace("\u2029", "\n"), True
        return edit.toPlainText(), False

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

    def current_location(self) -> tuple[str | None, int]:
        """The (file path, 1-based line) the caret is on, for "run to cursor" and friends.

        Returns (None, 0) when the active tab isn't a saved file -- the welcome tab, or
        a buffer that has never been written to disk and so has no path to map through
        the source map.
        """
        widget = self.currentWidget()
        if not isinstance(widget, CodeEdit):
            return None, 0
        path = widget.property("file_path")
        if not path:
            return None, 0
        return path, widget.textCursor().blockNumber() + 1

    def line_count(self) -> int:
        """How many lines the focused file has (0 if the tab isn't a text buffer).

        Lets "Go to Line" bound its input to the file rather than to an arbitrary number.
        """
        edit = self.currentWidget()
        return edit.document().blockCount() if isinstance(edit, QPlainTextEdit) else 0

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
        # A byte-order mark is *file* metadata, not text. Read as plain utf-8 it survives
        # as a U+FEFF character at position 0 -- invisible, and therefore something you
        # can insert a line in front of, which moves it into the middle of the file where
        # an assembler reads it as a stray label in column zero. (Exactly that happened:
        # marking a block from the memory plan inserted its comment above the BOM and
        # broke the build.) So: strip it on the way in, remember it, put it back on save,
        # and the file stays byte-identical while nothing in the editor can trip over it.
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        edit.setProperty("had_bom", text.startswith("﻿"))
        edit.setPlainText(text.lstrip("﻿"))
        edit.setProperty("file_path", key)  # the tab's identity, stable across reorders
        edit.document().setModified(False)
        edit.document().modificationChanged.connect(lambda _m, e=edit: self._update_title(e))
        index = self.addTab(edit, Path(path).name)
        self.setCurrentIndex(index)

    def replace_line(self, path: str, line: int, text: str) -> bool:
        """Replace one 1-based line of a file, through the editor. True if it happened.

        Deliberately *not* a write to disk. The memory map rewrites source when you drag a
        block somewhere else, and doing that behind the editor's back would be two bugs at
        once: an unsaved tab would silently lose the change (or clobber it on the next
        save), and there would be no way to take it back. Going through the document
        instead means the file opens where it changed, Ctrl+Z undoes it like any other
        edit, and it is saved when you save -- including by the save-all a build does.
        """
        self.open_file(path)
        edit = self.currentWidget()
        if not isinstance(edit, QPlainTextEdit):
            return False
        block = edit.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return False
        cursor = edit.textCursor()
        cursor.setPosition(block.position())
        cursor.setPosition(block.position() + block.length() - 1, QTextCursor.KeepAnchor)
        cursor.insertText(text)  # one undo step, and it marks the document modified
        edit.setTextCursor(cursor)
        edit.centerCursor()
        return True

    def insert_lines(self, path: str, line: int, texts: list) -> bool:
        """Insert lines before 1-based ``line``, through the editor. True if it happened.

        The companion to :meth:`replace_line`, for the one edit that is not a substitution:
        putting a block into another bank needs ``SLOT``/``PAGE`` *added* above its ``org``.
        One undo step for the whole insertion, for the same reasons as replace_line.
        """
        if not texts:
            return True
        self.open_file(path)
        edit = self.currentWidget()
        if not isinstance(edit, QPlainTextEdit):
            return False
        block = edit.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return False
        cursor = edit.textCursor()
        cursor.setPosition(block.position())
        cursor.insertText("\n".join(texts) + "\n")
        edit.setTextCursor(cursor)
        edit.centerCursor()
        return True

    def delete_line(self, path: str, line: int) -> bool:
        """Remove one 1-based line, through the editor. The third of the trio with
        :meth:`replace_line` and :meth:`insert_lines`, for taking an attribute back off."""
        self.open_file(path)
        edit = self.currentWidget()
        if not isinstance(edit, QPlainTextEdit):
            return False
        block = edit.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return False
        cursor = edit.textCursor()
        cursor.setPosition(block.position())
        cursor.setPosition(block.position() + block.length(), QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        edit.setTextCursor(cursor)
        edit.centerCursor()
        return True

    def close_files_under(self, path: str) -> list[str]:
        """Close every tab whose file is ``path`` or lives inside it. Returns what closed.

        Deleting a file from the project tree has to take its editor tab with it,
        otherwise the tab lingers over a file that no longer exists and the next Save All
        quietly recreates it.
        """
        target = Path(path).resolve()
        closed: list[str] = []
        for i in reversed(range(self.count())):
            widget = self.widget(i)
            file_path = widget.property("file_path") if widget else None
            if not file_path:
                continue
            resolved = Path(file_path)
            if resolved == target or target in resolved.parents:
                closed.append(file_path)
                self.removeTab(i)
        return closed

    def current_path(self) -> str | None:
        """The file in the focused tab, or None if the tab is not backed by a file.

        (The welcome tab isn't -- it has no ``file_path`` property.)
        """
        edit = self.currentWidget()
        if not isinstance(edit, QPlainTextEdit):
            return None
        return edit.property("file_path") or None

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
        text = edit.toPlainText()
        if edit.property("had_bom"):
            text = "﻿" + text  # restore what the file came with -- see open_file
        Path(path).write_text(text, encoding="utf-8")
        edit.document().setModified(False)
        # Saving a file of constants changes what every *other* tab's includes are worth,
        # and their own documents haven't changed, so nothing else would notice.
        for i in range(self.count()):
            widget = self.widget(i)
            if isinstance(widget, CodeEdit):
                widget.invalidate_symbols()

    def _update_title(self, edit) -> None:
        index = self.indexOf(edit)
        if index < 0:
            return
        name = Path(edit.property("file_path") or "untitled").name
        self.setTabText(index, "● {}".format(name) if edit.document().isModified() else name)

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

    def set_instruction_help(self, on: bool) -> None:
        """Turn hover help on or off for every tab, open or not yet created."""
        self._instruction_help = on
        for i in range(self.count()):
            widget = self.widget(i)
            if isinstance(widget, CodeEdit):
                widget.set_instruction_help(on)

    def _apply_special_chars(self, edit: QPlainTextEdit) -> None:
        option = edit.document().defaultTextOption()
        flags = option.flags()
        option.setFlags(flags | _SPECIAL_CHARS if self._show_special else flags & ~_SPECIAL_CHARS)
        edit.document().setDefaultTextOption(option)
