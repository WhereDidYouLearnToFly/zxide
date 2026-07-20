"""A syntax highlighter for Z80 assembly (sjasmplus flavour).

Colours mnemonics, assembler directives, registers, numbers (hex/bin/dec),
strings, labels, and comments. The palette matches the dark editor theme. It's a
line-at-a-time QSyntaxHighlighter: rules are applied in order, with strings and
comments applied last so a ';' turns the rest of the line into a comment.
"""

from __future__ import annotations

from PyQt5.QtCore import QRegularExpression
from PyQt5.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

# Z80 instruction mnemonics (including undocumented sll).
_MNEMONICS = (
    "adc add and bit call ccf cp cpd cpdr cpi cpir cpl daa dec di djnz ei ex exx "
    "halt im in inc ind indr ini inir jp jr ld ldd lddr ldi ldir neg nop or otdr "
    "otir out outd outi pop push res ret reti retn rl rla rlc rlca rld rr rra rrc "
    "rrca rrd rst sbc scf set sla sll sra srl sub xor"
).split()

# Common sjasmplus directives / pseudo-ops.
_DIRECTIVES = (
    "org device end include incbin equ db dw dd ds defb defw defs defm dc dz byte "
    "word align assert macro endm module endmodule struct proc endp savesna savetap "
    "savebin savehob output emptytap savesld page slot mmu dup edup rept endr repeat "
    "block if else endif ifdef ifndef define undefine export"
).split()

# 8- and 16-bit registers and flag conditions.
_REGISTERS = (
    "a f b c d e h l i r af bc de hl sp ix iy pc ixh ixl iyh iyl nz nc po pe"
).split()


def _fmt(color: str, *, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if italic:
        fmt.setFontItalic(True)
    return fmt


def _word_regex(words) -> QRegularExpression:
    pattern = r"\b(?:" + "|".join(words) + r")\b"
    return QRegularExpression(pattern, QRegularExpression.CaseInsensitiveOption)


class Z80Highlighter(QSyntaxHighlighter):
    """Highlights Z80 assembly in a QTextDocument."""

    def __init__(self, document):
        super().__init__(document)
        self._rules = [
            (_word_regex(_MNEMONICS), _fmt("#569cd6")),   # instructions -- blue
            (_word_regex(_DIRECTIVES), _fmt("#c586c0")),  # directives -- purple
            (_word_regex(_REGISTERS), _fmt("#9cdcfe")),   # registers -- light blue
            (QRegularExpression(r"(\$[0-9A-Fa-f]+|0x[0-9A-Fa-f]+|%[01]+|\b\d+\b)"),
             _fmt("#b5cea8")),                            # numbers -- green
        ]
        # Applied after the word rules so they win over them.
        self._label = (QRegularExpression(r"^\s*[A-Za-z_.@][\w.@]*:"), _fmt("#dcdcaa"))
        self._string = (QRegularExpression(r"\"[^\"]*\"|'[^']*'"), _fmt("#ce9178"))
        self._comment = (QRegularExpression(r";[^\n]*"), _fmt("#6a9955", italic=True))
        # Whitespace foreground -- invisible normally, but "Show special characters"
        # draws the space/tab markers in this colour, so keep it dim grey. Applied last
        # so every marker is grey regardless of surrounding tokens.
        self._whitespace = (QRegularExpression(r"[ \t]+"), _fmt("#5a5a5a"))

    def highlightBlock(self, text: str) -> None:
        for regex, fmt in self._rules:
            self._apply(regex, fmt, text)
        for regex, fmt in (self._label, self._string, self._comment, self._whitespace):
            self._apply(regex, fmt, text)

    def _apply(self, regex: QRegularExpression, fmt: QTextCharFormat, text: str) -> None:
        matches = regex.globalMatch(text)
        while matches.hasNext():
            match = matches.next()
            self.setFormat(match.capturedStart(), match.capturedLength(), fmt)
