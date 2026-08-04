"""Where a name is defined: labels, ``equ`` constants, macros and modules.

The question "what is this and where does it come from" is the one you ask most while
reading somebody's assembly -- including your own, six months on. In a Z80 project the
answer is nearly always in a different file: a label in one of a dozen includes, a
constant in a memory-map table, a macro in ``core/macros/``. Grepping finds it; jumping
to it is what an IDE is for.

This is the fourth module here that reads source rather than memory, and like the others
it reuses rather than re-parses:

* :func:`asm_meter.split_line` decides what a label *is* -- ``loop:`` and the harder
  column-zero ``loop  ld a,1`` -- so a definition and the assembly meter can never
  disagree about that.
* The include walk follows :mod:`asm_symbols`' shape, including its depth cap and its
  ``read_source`` hook, so a definition in an unsaved tab is found as readily as one on
  disk.

**Names are indexed twice inside a MODULE**, bare and qualified: ``init_im2`` written
inside ``MODULE interrupt`` is reachable as both ``init_im2`` (how the file itself writes
it) and ``interrupt.init_im2`` (how everyone else must). Looking up either finds it, which
is what makes "go to definition" work from a call site in another file.

What it does not do: expand macros, evaluate conditionals, or resolve which of two
same-named labels a given line actually meant. Where a name has several definitions they
are all returned, in the order the assembler would have seen them, and the caller offers
the choice rather than this module guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from zxemu_core.debug import asm_meter, asm_symbols

#: Matches ``asm_symbols``: deep enough for real projects, shallow enough to stay instant.
MAX_INCLUDE_DEPTH = 8

#: ``MACRO NAME args`` -- sjasmplus's usual form. The other form, ``NAME MACRO args``,
#: arrives here as a label plus a ``macro`` statement and is caught without a pattern.
_MACRO = re.compile(r"^macro\s+([A-Za-z_@.][A-Za-z0-9_@.]*)", re.IGNORECASE)
_MODULE = re.compile(r"^module\s+([A-Za-z_@.][A-Za-z0-9_@.]*)", re.IGNORECASE)
_ASSIGNS = ("equ", "defl", "=")

#: The characters a name can be made of, dots included: a qualified ``interrupt.init_im2``
#: is one name, and picking only ``init_im2`` out of it would lose which module was meant.
_NAME_CHARS = re.compile(r"[A-Za-z0-9_@.]")


@dataclass(frozen=True)
class Definition:
    """One place a name is introduced."""

    name: str        # as written, qualified where a MODULE encloses it
    kind: str        # "label" | "constant" | "macro" | "module"
    path: str        # absolute path of the file holding it
    origin: str      # how to show that file to a human
    line: int        # 1-based
    text: str        # the defining line, stripped -- a preview for a chooser

    def describe(self) -> str:
        return "{} {} — {}:{}".format(self.kind, self.name, self.origin, self.line)


def collect(text: str, path: str = "", base_dir=None, read_source=None) -> dict:
    """Index every definition in ``text`` and everything it includes.

    Returns ``{lower-cased name: [Definition, ...]}``. A name defined in more than one
    place keeps all of them: two files can define the same label, and which one the
    assembler takes depends on include order this does not attempt to model.
    """
    reader = read_source if read_source is not None else _read_file
    table: dict = {}
    seen: set = set()
    _index(text, path, table, Path(base_dir) if base_dir else None, reader, seen, MAX_INCLUDE_DEPTH)
    return table


def _index(text, path, table, base, reader, seen, depth) -> None:
    origin = Path(path).name if path else ""
    modules: list = []
    for number, raw_line in enumerate(text.splitlines(), start=1):
        # A UTF-8 BOM on line 1 would otherwise register as a label of its own.
        line = raw_line.lstrip("﻿")
        label, statements = asm_meter.split_line(line)
        head = statements[0] if statements else ""
        mnemonic = head.split(None, 1)[0].lower() if head else ""

        if mnemonic in asm_meter.MODULE_CLOSE and modules:
            modules.pop()
            continue
        module_match = _MODULE.match(head) if head else None
        if module_match is not None:
            _add(table, module_match.group(1), "module", path, origin, number, line, modules)
            modules.append(module_match.group(1))
            continue
        macro_match = _MACRO.match(head) if head else None
        if macro_match is not None:
            _add(table, macro_match.group(1), "macro", path, origin, number, line, [])
            continue
        if label:
            # `NAME MACRO args` -- the other macro form, seen as a label plus a statement.
            kind = "macro" if mnemonic == "macro" else ("constant" if mnemonic in _ASSIGNS else "label")
            _add(table, label, kind, path, origin, number, line, [] if kind == "macro" else modules)

    if base is None or depth <= 0:
        return
    for relative in asm_symbols.include_paths(text):
        try:
            included = (base / relative).resolve()
        except OSError:
            continue
        key = str(included).lower()
        if key in seen:
            continue
        seen.add(key)
        content = reader(str(included))
        if content is not None:
            _index(content, str(included), table, included.parent, reader, seen, depth - 1)


def _add(table: dict, name: str, kind: str, path: str, origin: str, line: int, text: str, modules: list) -> None:
    """Record a definition under its own name, and under its qualified name inside a MODULE."""
    names = [name]
    if modules:
        names.append("{}.{}".format(".".join(modules), name))
    for written in names:
        entry = Definition(name=written, kind=kind, path=path, origin=origin, line=line, text=text.strip())
        table.setdefault(written.lower(), []).append(entry)


def name_at(line: str, column: int) -> str:
    """The identifier under ``column``, dots included, or "" if there isn't one.

    Dots are part of the name so that clicking anywhere in ``interrupt.init_im2`` asks
    about that one thing, rather than about whichever half the caret happened to be in.
    """
    if not line:
        return ""
    column = max(0, min(column, len(line) - 1))
    if not _NAME_CHARS.match(line[column]):
        column -= 1  # just past the end of a name is still that name, as in every editor
        if column < 0 or not _NAME_CHARS.match(line[column]):
            return ""
    start = column
    while start > 0 and _NAME_CHARS.match(line[start - 1]):
        start -= 1
    end = column
    while end + 1 < len(line) and _NAME_CHARS.match(line[end + 1]):
        end += 1
    return line[start:end + 1].strip(".")


def find(name: str, table: dict) -> list:
    """Definitions of ``name``: exact first, then the same label under any module.

    The fallback matters because a file inside ``MODULE interrupt`` calls its own labels
    bare, while the rest of the project must qualify them -- and jumping from either
    spelling should land in the same place.
    """
    if not name:
        return []
    exact = table.get(name.lower())
    if exact:
        return exact
    suffix = "." + name.lower()
    found = []
    for key, entries in table.items():
        if key.endswith(suffix):
            found.extend(entries)
    return found


def _read_file(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
