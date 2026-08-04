"""A syntax highlighter for Z80 assembly (sjasmplus flavour) -- and the Lua inside it.

Colours mnemonics, assembler directives, registers, numbers (hex/bin/dec),
strings, labels, and comments. The palette matches the dark editor theme. It's a
line-at-a-time QSyntaxHighlighter: rules are applied in order, with strings and
comments applied last so a ';' turns the rest of the line into a comment.

**A ``.asm`` file here can contain a second language.** sjasmplus embeds Lua, and a
``LUA`` / ``ENDLUA`` block is ordinary Lua source sitting in the middle of assembly --
zxide's memory dumper generates exactly that to write a snapshot with a correct register
header. Highlighting it as assembly is actively misleading: Lua's ``--`` comments would
be read as a subtraction, its ``local`` and ``function`` as labels, and its strings would
be the only thing coloured correctly.

So the highlighter is a two-state machine. Assembly rules apply outside the block, Lua
rules inside it, and the state is carried across lines with ``setCurrentBlockState`` --
which is the only way a line-at-a-time highlighter can know it is halfway through
something that started earlier.
"""

from __future__ import annotations

from PyQt5.QtCore import QRegularExpression
from PyQt5.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from zxemu_core.debug.asm_hidden import SUSPECTS

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
    "word align assert macro endm module endmodule endmod struct proc endp savesna savetap "
    "savebin savehob output emptytap savesld page slot mmu dup edup rept endr repeat "
    "block if else endif ifdef ifndef define undefine export lua endlua"
).split()

# Lua 5.4 keywords -- sjasmplus embeds Lua, so a LUA/ENDLUA block is real Lua source.
_LUA_KEYWORDS = (
    "and break do else elseif end false for function goto if in local nil not or "
    "repeat return then true until while self"
).split()

# The assembler's own Lua API. Worth its own colour: these are the whole reason there is
# Lua in an .asm file at all, and they are what a reader will be looking for.
_LUA_API = (
    "sj zx print assert error pairs ipairs tostring tonumber type string table math io os"
).split()

#: A ``LUA`` block opener -- optionally followed by a pass selector (``LUA PASS1``,
#: ``ALLPASS``), which is why this is a prefix match rather than a whole-line one.
_LUA_START = QRegularExpression(r"^\s*lua\b", QRegularExpression.CaseInsensitiveOption)
_LUA_END = QRegularExpression(r"^\s*endlua\b", QRegularExpression.CaseInsensitiveOption)

#: Block states carried between lines. Qt uses -1 for "no state", so start at 0.
_STATE_ASM = 0
_STATE_LUA = 1

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



_INVISIBLE = QTextCharFormat()
_INVISIBLE.setBackground(QColor("#8c2f39"))
_INVISIBLE.setToolTip("Invisible character — not valid in assembly source")

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

        # Lua, for the LUA/ENDLUA blocks sjasmplus allows. Deliberately the same palette
        # as the assembly rules -- keywords blue, strings orange, comments green -- so the
        # file reads as one document rather than two pasted together, while still being
        # obviously a different language.
        self._lua_rules = [
            (_word_regex(_LUA_KEYWORDS), _fmt("#569cd6")),
            (_word_regex(_LUA_API), _fmt("#4ec9b0")),     # the sj./zx. API -- teal
            (QRegularExpression(r"(\b0[xX][0-9A-Fa-f]+\b|\b\d+\b)"), _fmt("#b5cea8")),
        ]
        # Lua comments start with `--`, not `;`. Getting this wrong is the most visible
        # failure: every comment in the block would read as an arithmetic expression.
        self._lua_string = (QRegularExpression(r"\"[^\"]*\"|'[^']*'|\[\[.*?\]\]"),
                            _fmt("#ce9178"))
        self._lua_comment = (QRegularExpression(r"--[^\n]*"), _fmt("#6a9955", italic=True))

    def highlightBlock(self, text: str) -> None:
        """Highlight one line, in whichever language it belongs to.

        The state from the previous line decides which, and the ``LUA``/``ENDLUA`` lines
        themselves are treated as assembly directives -- they are the assembler's syntax,
        not Lua's.
        """
        state = self.previousBlockState()
        if state == -1:
            state = _STATE_ASM

        if state == _STATE_LUA:
            if _LUA_END.match(text).hasMatch():
                self._highlight_asm(text)          # ENDLUA is a directive
                state = _STATE_ASM
            else:
                self._highlight_lua(text)
        else:
            self._highlight_asm(text)
            if _LUA_START.match(text).hasMatch():
                state = _STATE_LUA
        self._mark_invisible(text)
        self.setCurrentBlockState(state)


    def _mark_invisible(self, text: str) -> None:
        """Paint a red block over any character that shows nothing.

        Last, so it wins over every syntax colour -- the whole point is that it cannot be
        missed. Applied in both languages and inside strings and comments, because an
        invisible character is a problem wherever it is, and the one place people assume
        it is harmless (a comment) is where pasted text usually lands.
        """
        if not text:
            return
        for column, character in enumerate(text):
            if character in SUSPECTS:
                self.setFormat(column, 1, _INVISIBLE)

    def _highlight_asm(self, text: str) -> None:
        for regex, fmt in self._rules:
            self._apply(regex, fmt, text)
        for regex, fmt in (self._label, self._string, self._comment, self._whitespace):
            self._apply(regex, fmt, text)

    def _highlight_lua(self, text: str) -> None:
        for regex, fmt in self._lua_rules:
            self._apply(regex, fmt, text)
        for regex, fmt in (self._lua_string, self._lua_comment, self._whitespace):
            self._apply(regex, fmt, text)

    def _apply(self, regex: QRegularExpression, fmt: QTextCharFormat, text: str) -> None:
        matches = regex.globalMatch(text)
        while matches.hasNext():
            match = matches.next()
            self.setFormat(match.capturedStart(), match.capturedLength(), fmt)
