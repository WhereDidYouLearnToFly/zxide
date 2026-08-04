"""Characters that are in the file, mean something to the assembler, and show nothing.

Every one of these is legal UTF-8 and legal to have in a text file. What makes them worth
a module is that they are **invisible**: the line looks right, the assembler complains
about a character it cannot print, and you spend the next hour doubting the parts that are
fine. That happened here -- three bytes marking a file as UTF-8 ended up in column one
after a line was inserted above them, and sjasmplus said only::

    error: Invalid labelname:

with nothing after the colon. Everything the eye could check was correct.

So the rule this module exists to serve is: **anything the editor cannot draw, it must
mark.** Finding them is trivial; the value is entirely in nobody having to know they exist.

Deliberately a short, named list rather than "every non-ASCII character". Comments and
string literals hold accented letters, box-drawing, arrows and emoji in real projects, and
flagging those would be noise that teaches you to ignore the warning.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zxemu_core.debug import asm_symbols

#: What each suspect is, in words rather than in Unicode's vocabulary -- the message has to
#: mean something to somebody who has never heard of a byte-order mark.
SUSPECTS = {
    "﻿": "file-type marker (invisible; belongs only at the very start of a file)",
    " ": "non-breaking space (looks exactly like a space; usually pasted from a browser or PDF)",
    "​": "zero-width space (invisible; can sit inside a label and split it in two)",
    "‌": "zero-width non-joiner (invisible)",
    "‍": "zero-width joiner (invisible)",
    "⁠": "word joiner (invisible)",
    " ": "line separator (a line break the assembler does not count as one)",
    " ": "paragraph separator (a line break the assembler does not count as one)",
    "‪": "text-direction mark (invisible; can reorder how the line reads)",
    "‫": "text-direction mark (invisible; can reorder how the line reads)",
    "‬": "text-direction mark (invisible)",
    "‭": "text-direction mark (invisible; can reorder how the line reads)",
    "‮": "text-direction mark (invisible; can reorder how the line reads)",
    "­": "soft hyphen (invisible until a line wraps)",
}

#: Matches ``asm_symbols``: deep enough for real projects, shallow enough to stay instant.
MAX_INCLUDE_DEPTH = 8


@dataclass(frozen=True)
class Finding:
    """One invisible character, located precisely enough to click on."""

    origin: str       # the file, as it should be shown
    path: str         # absolute, for opening it
    line: int         # 1-based
    column: int       # 1-based
    character: str
    description: str

    def describe(self) -> str:
        return "{}:{}:{} — {}".format(self.origin, self.line, self.column, self.description)


def find(text: str, origin: str = "", path: str = "") -> list:
    """Every suspect character in one file.

    A marker on line 1 column 1 is *not* reported: that is the ordinary, harmless way a
    UTF-8 file announces itself, and every assembler skips it. It only becomes a problem
    once something else is above it -- which is exactly what line > 1 means here.
    """
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        for column, character in enumerate(line, start=1):
            if character not in SUSPECTS:
                continue
            if character == "﻿" and number == 1 and column == 1:
                continue
            found.append(Finding(origin or path, path, number, column, character, SUSPECTS[character]))
    return found


def scan(text: str, path: str = "", base_dir=None, read_source=None, depth: int = MAX_INCLUDE_DEPTH, seen=None) -> list:
    """Every suspect character in this file and everything it includes.

    Follows includes because the file you have open is rarely the one at fault: an
    invisible character arrives with a paste into whichever module was being edited that
    day, and stays there until a build fails somewhere that looks unrelated.
    """
    reader = read_source if read_source is not None else _read_file
    seen = seen if seen is not None else set()
    findings = find(text, Path(path).name if path else "", path)
    if base_dir is None or depth <= 0:
        return findings
    for relative in asm_symbols.include_paths(text):
        try:
            included = (Path(base_dir) / relative).resolve()
        except OSError:
            continue
        key = str(included).lower()
        if key in seen:
            continue
        seen.add(key)
        content = reader(str(included))
        if content is not None:
            findings.extend(scan(content, str(included), included.parent, reader, depth - 1, seen))
    return findings


def _read_file(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
