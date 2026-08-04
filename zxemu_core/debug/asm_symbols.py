"""Constants defined with ``equ`` -- the values behind the editor's hover help.

Reading ``ld hl,SCREEN_ADDR`` tells you nothing about where that write lands, and the
answer is usually two files away in a constants include. This module finds those
definitions and works out what they come to, so hover help can say ``SCREEN_ADDR = 16384
($4000)`` without you leaving the line you are reading.

It works on *source text*, not on a build. That is deliberate: the values must be there
while you type, before anything assembles, and for a file that never assembles cleanly at
all. The cost is that anything the assembler alone can know -- ``$`` (the current address),
macro arguments, labels -- is simply not resolvable here, and unresolved constants show
their expression instead of a value rather than guessing. Addresses of real *labels* are a
different question with a different answer: they come from the build's SLD map
(:mod:`zxemu_ui.workspace.sld`), which knows where the code actually landed.

Includes are followed through a caller-supplied reader rather than always going to disk,
because the editor's copy of a file is the one you are looking at -- reading the saved
version would show stale values for a constant you just changed but haven't saved.

Expressions are evaluated by rewriting assembler notation ($4000, %1010, 0FFh, 'A') into
Python and walking the parse tree by hand over a small whitelist of operators. Nothing is
executed: an expression using anything outside that whitelist yields no value at all,
which is the honest answer and much safer than being clever.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from zxemu_core.debug import asm_meter

_MAX_INCLUDE_DEPTH = 8  # deep enough for real projects, shallow enough to stay instant
_MAX_SHIFT = 64  # a shift bigger than this is a typo, and would build a gigantic integer

# ``NAME: equ expr``, ``NAME equ expr``, ``NAME = expr``, ``NAME defl expr``. The colon is
# optional because both styles are common, and sjasmplus accepts either.
_DEFINITION = re.compile(r"^\s*([A-Za-z_@.][A-Za-z0-9_@.]*)\s*:?\s*(?:(?:equ|defl)\s+|=\s*)(.+)$", re.IGNORECASE)
# ``DEFINE NAME text`` -- a text substitution, but used for constants often enough to count.
_DEFINE = re.compile(r"^\s*define\s+([A-Za-z_@.][A-Za-z0-9_@.]*)\s+(.+)$", re.IGNORECASE)
_INCLUDE = re.compile(r"""^\s*include\s+["'<]?([^"'>\s;]+)""", re.IGNORECASE)
_IDENTIFIER = re.compile(r"[A-Za-z_@.][A-Za-z0-9_@.]*")

# Names that are never a constant reference even if something in the file shadows them, so
# that a constant unluckily called ``c`` doesn't make every ``jr c,loop`` sprout a tooltip.
_REGISTERS = frozenset(
    "a b c d e h l i r f af bc de hl sp ix iy pc ixh ixl iyh iyl af' nz z nc po pe p m".split()
)

_TOKEN = re.compile(
    r"""
      (?P<hexprefix>[$\#][0-9A-Fa-f]+)
    | (?P<hexsuffix>\d[0-9A-Fa-f]*[hH]\b)
    | (?P<binsuffix>[01]+[bB]\b)
    | (?P<binpercent>%[01]+)
    | (?P<number>0[xX][0-9A-Fa-f]+|0[bB][01]+|\d+)
    | (?P<char>'(?:[^'\\]|\\.)'|\"(?:[^\"\\]|\\.)\")
    | (?P<name>[A-Za-z_@.][A-Za-z0-9_@.]*)
    | (?P<shift><<|>>)
    | (?P<op>[-+*/%&|^~()])
    | (?P<space>\s+)
    """,
    re.VERBOSE,
)


@dataclass
class Constant:
    """One ``equ`` definition: the name as written, what it was set to, and its value."""

    name: str               # as written in the source, so the tooltip echoes your spelling
    expression: str         # the right-hand side, verbatim
    value: int | None = None  # what it comes to, or None when it can't be worked out here
    origin: str = ""        # file it came from, for display; empty for the file being edited
    # Where the definition lives, exactly. Hover help only ever needed the value, but the
    # memory map *edits* these lines -- moving a block of code means rewriting the one
    # `equ` its `org` points at -- and for that "somewhere in a file called memmap.i" is
    # not enough. The path is the resolved one, so an include in a subfolder is findable.
    path: str = ""
    line: int = 0           # 1-based; 0 when unknown


def definitions(text: str, origin: str = "", path: str = "") -> dict[str, Constant]:
    """Every constant defined in one file, keyed by lower-cased name.

    The first definition of a name wins. Redefinition is an error for ``equ`` anyway, and
    for the reassignable forms (``defl``, ``=``) any single answer would be a guess about
    which line the reader is between -- the first one at least matches where the name was
    introduced.
    """
    found: dict[str, Constant] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        body = asm_meter.strip_comment(line)
        match = _DEFINITION.match(body) or _DEFINE.match(body)
        if match is None:
            continue
        name, expression = match.group(1), match.group(2).strip()
        key = name.lower()
        if expression and key not in found and key not in _REGISTERS:
            found[key] = Constant(name=name, expression=expression, origin=origin, path=path, line=number)
    return found


def include_paths(text: str) -> list[str]:
    """The files this source pulls in with ``include``, in the order they appear."""
    paths = []
    for line in text.splitlines():
        match = _INCLUDE.match(asm_meter.strip_comment(line))
        if match is not None:
            paths.append(match.group(1))
    return paths


def _read_file(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def collect(text: str, base_dir=None, read_source=None) -> dict[str, Constant]:
    """Constants from this text plus everything it includes, with values worked out.

    ``read_source`` maps a path to its text (or None if it can't be had); the editor passes
    one that prefers the open, possibly-unsaved tab over the file on disk. Included files
    only contribute names the outer file hasn't already defined, matching the assembler's
    "first definition wins" and keeping a local override on top.
    """
    reader = read_source if read_source is not None else _read_file
    table = definitions(text)
    if base_dir is not None:
        seen: set[str] = set()
        _follow_includes(text, Path(base_dir), reader, table, seen, _MAX_INCLUDE_DEPTH)
    return resolve(table)


def _follow_includes(text: str, base: Path, reader, table: dict[str, Constant], seen: set[str], depth: int) -> None:
    """Merge in the constants of every file ``text`` includes, depth-first."""
    if depth <= 0:
        return
    for relative in include_paths(text):
        try:
            path = (base / relative).resolve()
        except OSError:
            continue
        key = str(path).lower()
        if key in seen:
            continue  # a diamond of includes, or a cycle -- either way, once is enough
        seen.add(key)
        included = reader(str(path))
        if included is None:
            continue
        for name, constant in definitions(included, origin=path.name, path=str(path)).items():
            table.setdefault(name, constant)
        _follow_includes(included, path.parent, reader, table, seen, depth - 1)


def resolve(table: dict[str, Constant]) -> dict[str, Constant]:
    """Fill in every constant's value, in place, leaving None where it can't be found."""
    for name, constant in table.items():
        constant.value = _evaluate(constant.expression, table, {name})
    return table


def evaluate(expression: str, table: dict[str, Constant] | None = None) -> int | None:
    """What an assembler expression comes to, or None if it can't be worked out here."""
    return _evaluate(expression, table or {}, set())


def references(line: str, table: dict[str, Constant] | None) -> list[Constant]:
    """The constants named on this source line, in the order they are written.

    Quoted text is dropped first, so ``db "COUNT is 4"`` doesn't report a constant called
    COUNT that the line only mentions in a message.
    """
    if not table:
        return []
    body = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", " ", asm_meter.strip_comment(line))
    found: list[Constant] = []
    for match in _IDENTIFIER.finditer(body):
        constant = table.get(match.group(0).lower())
        if constant is not None and constant not in found:
            found.append(constant)
    return found


# --- expression evaluation -----------------------------------------------------------------


def _evaluate(expression: str, table: dict[str, Constant], resolving: set[str]) -> int | None:
    """Evaluate one expression, resolving names through ``table``.

    ``resolving`` holds the names currently being worked out, so a constant defined in
    terms of itself gives up instead of recursing forever.
    """
    source = _as_python(expression, table, resolving)
    if source is None:
        return None
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError:
        return None
    return _value_of(tree.body)


def _as_python(expression: str, table: dict[str, Constant], resolving: set[str]) -> str | None:
    """Rewrite assembler notation as Python source, or None if anything is unrecognised.

    Names are substituted as their *values* rather than left for the parser, which is what
    makes ``SCREEN_END: equ SCREEN + 6912`` resolve: one unknown name anywhere makes the
    whole expression unknown, which is the answer we want to show.
    """
    parts: list[str] = []
    position = 0
    previous_was_value = False  # tells `%` apart: modulo after a value, binary prefix before
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        if match is None:
            return None  # `$` for the current address, `!`, `<`, ... -- not ours to answer
        kind, token = match.lastgroup, match.group(0)
        position = match.end()

        if kind == "space":
            continue
        if kind == "binpercent" and previous_was_value:
            parts.append("%")  # a modulo that happened to be followed by 0s and 1s
            position = match.start() + 1
            previous_was_value = False
            continue

        if kind in ("hexprefix", "hexsuffix", "binsuffix", "number"):
            number = asm_meter.parse_number(token)
        elif kind == "binpercent":
            number = asm_meter.parse_number(token)
        elif kind == "char":
            inner = token[1:-1]
            if len(inner) == 2 and inner[0] == "\\":
                inner = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "\\": "\\", "'": "'", '"': '"'}.get(inner[1], "")
            number = ord(inner) if len(inner) == 1 else None
        elif kind == "name":
            number = _value_of_name(token, table, resolving)
        else:
            parts.append(token)
            previous_was_value = token == ")"
            continue

        if number is None:
            return None
        parts.append("({})".format(number))  # bracketed so a negative value can't glue on
        previous_was_value = True
    # `/` is integer division everywhere in assembly; Python's `/` would give a float.
    return "".join(parts).replace("/", "//")


def _value_of_name(token: str, table: dict[str, Constant], resolving: set[str]) -> int | None:
    key = token.lower()
    if key in resolving:
        return None  # defined in terms of itself, directly or through a chain
    constant = table.get(key)
    if constant is None:
        return None
    if constant.value is not None:
        return constant.value
    resolving.add(key)
    try:
        return _evaluate(constant.expression, table, resolving)
    finally:
        resolving.discard(key)


def _value_of(node) -> int | None:
    """Walk the parse tree by hand: only integers and the operators assemblers offer."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, int) and not isinstance(node.value, bool) else None
    if isinstance(node, ast.UnaryOp):
        operand = _value_of(node.operand)
        if operand is None:
            return None
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        if isinstance(node.op, ast.Invert):
            return ~operand
        return None
    if not isinstance(node, ast.BinOp):
        return None
    left, right = _value_of(node.left), _value_of(node.right)
    if left is None or right is None:
        return None
    try:
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.BitAnd):
            return left & right
        if isinstance(node.op, ast.BitOr):
            return left | right
        if isinstance(node.op, ast.BitXor):
            return left ^ right
        if isinstance(node.op, (ast.LShift, ast.RShift)):
            if not 0 <= right <= _MAX_SHIFT:
                return None  # a mistyped shift would otherwise build a colossal integer
            return left << right if isinstance(node.op, ast.LShift) else left >> right
    except (ZeroDivisionError, ValueError):
        return None
    return None
