"""The Z80 Assembly Meter: how many bytes and T-states a piece of source costs.

On a machine with 48K of RAM and 69888 T-states per frame, "does this fit" and "does
this finish in time" are the two questions that decide whether a routine works. Both are
answerable by reading the source -- you don't need to assemble anything, and you
certainly don't need to run it -- but only if you have the whole instruction table
memorised. This module *is* that table, so selecting a few lines in the editor answers
both questions immediately.

    ld a,(hl)     ; 1 byte,  7T
    inc hl        ; 1 byte,  6T
    djnz loop     ; 2 bytes, 13T taken / 8T on the last pass

That last line is why a cost is a *range*: conditional jumps, calls, returns and the
repeating block instructions take one time when they branch and another when they don't.
The meter reports both ends rather than picking one and being quietly wrong half the
time.

**Scope, stated honestly.** The counts are the published Z80 figures for an uncontended
machine -- no ULA memory contention (which depends on where the code sits and when the
beam is, neither of which source text can know) and no M1 wait states. Data directives
(``db``/``dw``/``ds``) count toward bytes and contribute no time. Anything the meter does
not recognise -- a macro invocation, an ``incbin`` whose file it cannot see -- is counted
as *unknown* and reported alongside the totals, so a number is never quietly short.

The decoder in ``zxemu_core.debug.disassembler`` goes the other way (bytes to text) and
carries no timing, so there is nothing here to share with it: this is a source-text
table, and the two would only be coupled by coincidence.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- results ---------------------------------------------------------------------------


@dataclass
class MeterResult:
    """What a run of source costs. ``t_states_min``/``max`` differ where branches do."""

    instructions: int = 0
    code_bytes: int = 0
    data_bytes: int = 0
    t_states_min: int = 0
    t_states_max: int = 0
    unknown: int = 0  # statements the table didn't recognise (macros, unsupported directives)

    @property
    def total_bytes(self) -> int:
        return self.code_bytes + self.data_bytes

    @property
    def has_time_range(self) -> bool:
        return self.t_states_min != self.t_states_max

    def add(self, other: "MeterResult") -> None:
        self.instructions += other.instructions
        self.code_bytes += other.code_bytes
        self.data_bytes += other.data_bytes
        self.t_states_min += other.t_states_min
        self.t_states_max += other.t_states_max
        self.unknown += other.unknown


# --- operand classification ------------------------------------------------------------
#
# Every operand is reduced to a set of *tags*, and a table rule matches when each of its
# slots names a tag the operand has. Tags rather than one class per operand because a
# token can legitimately be more than one thing: `c` is an 8-bit register in `ld c,a` and
# a condition in `jp c,label`, and which one it is depends on the mnemonic, which is
# exactly what the rule expresses.

_TAGS: dict[str, frozenset[str]] = {
    "a": frozenset({"a", "r8"}),
    "b": frozenset({"r8"}),
    "c": frozenset({"c", "r8", "cc"}),  # also the carry condition
    "d": frozenset({"r8"}),
    "e": frozenset({"r8"}),
    "h": frozenset({"r8"}),
    "l": frozenset({"r8"}),
    "i": frozenset({"reg_i"}),
    "r": frozenset({"reg_r"}),
    "f": frozenset({"f"}),
    "nz": frozenset({"cc"}),
    "z": frozenset({"cc"}),
    "nc": frozenset({"cc"}),
    "po": frozenset({"cc"}),
    "pe": frozenset({"cc"}),
    "p": frozenset({"cc"}),
    "m": frozenset({"cc"}),
    "bc": frozenset({"bc", "rp", "rp2"}),
    "de": frozenset({"de", "rp", "rp2"}),
    "hl": frozenset({"hl", "rp", "rp2"}),
    "sp": frozenset({"sp", "rp"}),
    "af": frozenset({"af", "rp2"}),
    "af'": frozenset({"afx"}),
    "ix": frozenset({"ix", "ii"}),
    "iy": frozenset({"iy", "ii"}),
    "(hl)": frozenset({"(hl)"}),
    "(bc)": frozenset({"(bc)"}),
    "(de)": frozenset({"(de)"}),
    "(sp)": frozenset({"(sp)"}),
    "(c)": frozenset({"(c)"}),
}

# The undocumented index-register halves, in every spelling the common assemblers accept.
_INDEX_HALVES = frozenset(
    {"ixh", "ixl", "iyh", "iyl", "xh", "xl", "yh", "yl", "hx", "lx", "hy", "ly"}
)

_IMMEDIATE = frozenset({"n"})
_INDEXED = frozenset({"(i+d)"})
_INDIRECT_INDEX = frozenset({"(ii)", "(i+d)"})  # `(ix)` is both `jp (ix)` and `ld a,(ix+0)`
_ABSOLUTE = frozenset({"(nn)"})


def classify(operand: str) -> frozenset[str]:
    """One operand's tag set -- the vocabulary the instruction table is written in."""
    token = operand.strip().lower()
    if not token:
        return frozenset()
    if token in _TAGS:
        return _TAGS[token]
    if token in _INDEX_HALVES:
        return frozenset({"rx"})
    if token.startswith("(") and token.endswith(")"):
        inner = token[1:-1].strip()
        if inner in ("ix", "iy"):
            return _INDIRECT_INDEX
        if inner.startswith(("ix", "iy")) and len(inner) > 2 and not inner[2].isalnum():
            return _INDEXED
        return _ABSOLUTE
    return _IMMEDIATE


# --- the instruction table --------------------------------------------------------------
#
# One entry per mnemonic: an ordered list of (operand pattern, bytes, T-min, T-max). A
# pattern slot may offer alternatives with "|". First match wins, so where two rules could
# both apply the more specific one comes first.

Rule = tuple[tuple[str, ...], int, int, int]

_SIMPLE: dict[str, tuple[int, int]] = {  # no operands, one cost
    "nop": (1, 4),
    "halt": (1, 4),
    "di": (1, 4),
    "ei": (1, 4),
    "daa": (1, 4),
    "cpl": (1, 4),
    "ccf": (1, 4),
    "scf": (1, 4),
    "rlca": (1, 4),
    "rrca": (1, 4),
    "rla": (1, 4),
    "rra": (1, 4),
    "exx": (1, 4),
    "neg": (2, 8),
    "reti": (2, 14),
    "retn": (2, 14),
    "rld": (2, 18),
    "rrd": (2, 18),
    # Block instructions: the non-repeating forms are one flat cost...
    "ldi": (2, 16),
    "ldd": (2, 16),
    "cpi": (2, 16),
    "cpd": (2, 16),
    "ini": (2, 16),
    "ind": (2, 16),
    "outi": (2, 16),
    "outd": (2, 16),
}

# ...and the repeating forms cost 21T per iteration, 16T on the pass that ends the loop.
_REPEATING_BLOCK: dict[str, tuple[int, int, int]] = {
    name: (2, 16, 21) for name in ("ldir", "lddr", "cpir", "cpdr", "inir", "indr", "otir", "otdr")
}

# The 8-bit ALU group: identical shapes for all eight operations, each usable with or
# without the explicit `a,` destination that assemblers allow you to omit.
_ALU_RULES: tuple[Rule, ...] = (
    (("a", "r8"), 1, 4, 4),
    (("a", "(hl)"), 1, 7, 7),
    (("a", "(i+d)"), 3, 19, 19),
    (("a", "rx"), 2, 8, 8),
    (("a", "n"), 2, 7, 7),
    (("r8",), 1, 4, 4),
    (("(hl)",), 1, 7, 7),
    (("(i+d)",), 3, 19, 19),
    (("rx",), 2, 8, 8),
    (("n",), 2, 7, 7),
)

# The CB rotate/shift group -- same shapes for all eight.
_ROTATE_RULES: tuple[Rule, ...] = (
    (("r8",), 2, 8, 8),
    (("(hl)",), 2, 15, 15),
    (("(i+d)",), 4, 23, 23),
    (("(i+d)", "r8"), 4, 23, 23),  # undocumented: also copies the result into a register
)

_TABLE: dict[str, tuple[Rule, ...]] = {
    "ld": (
        # 16-bit forms first: `ld hl,nn` must not be read as an 8-bit load.
        (("sp", "hl"), 1, 6, 6),
        (("sp", "ii"), 2, 10, 10),
        (("ii", "(nn)"), 4, 20, 20),
        (("ii", "n"), 4, 14, 14),
        (("hl", "(nn)"), 3, 16, 16),
        (("bc|de|sp", "(nn)"), 4, 20, 20),
        (("rp", "n"), 3, 10, 10),
        (("(nn)", "hl"), 3, 16, 16),
        (("(nn)", "ii"), 4, 20, 20),
        (("(nn)", "bc|de|sp"), 4, 20, 20),
        # The interrupt/refresh registers.
        (("a", "reg_i|reg_r"), 2, 9, 9),
        (("reg_i|reg_r", "a"), 2, 9, 9),
        # 8-bit loads through a register pair.
        (("a", "(bc)|(de)"), 1, 7, 7),
        (("(bc)|(de)", "a"), 1, 7, 7),
        (("a", "(nn)"), 3, 13, 13),
        (("(nn)", "a"), 3, 13, 13),
        # Indexed.
        (("(i+d)", "r8"), 3, 19, 19),
        (("r8", "(i+d)"), 3, 19, 19),
        (("(i+d)", "n"), 4, 19, 19),
        # The undocumented index halves.
        (("rx", "rx|r8"), 2, 8, 8),
        (("r8", "rx"), 2, 8, 8),
        (("rx", "n"), 3, 11, 11),
        # Plain 8-bit.
        (("(hl)", "r8"), 1, 7, 7),
        (("r8", "(hl)"), 1, 7, 7),
        (("(hl)", "n"), 2, 10, 10),
        (("r8", "r8"), 1, 4, 4),
        (("r8", "n"), 2, 7, 7),
    ),
    "push": ((("rp2",), 1, 11, 11), (("ii",), 2, 15, 15)),
    "pop": ((("rp2",), 1, 10, 10), (("ii",), 2, 14, 14)),
    "ex": (
        (("de", "hl"), 1, 4, 4),
        (("af", "afx|af"), 1, 4, 4),
        (("(sp)", "hl"), 1, 19, 19),
        (("(sp)", "ii"), 2, 23, 23),
    ),
    "add": (
        (("hl", "rp"), 1, 11, 11),
        (("ix", "bc|de|ix|sp"), 2, 15, 15),
        (("iy", "bc|de|iy|sp"), 2, 15, 15),
        *_ALU_RULES,
    ),
    "adc": ((("hl", "rp"), 2, 15, 15), *_ALU_RULES),
    "sbc": ((("hl", "rp"), 2, 15, 15), *_ALU_RULES),
    "sub": _ALU_RULES,
    "and": _ALU_RULES,
    "xor": _ALU_RULES,
    "or": _ALU_RULES,
    "cp": _ALU_RULES,
    "inc": (
        (("r8",), 1, 4, 4),
        (("(hl)",), 1, 11, 11),
        (("(i+d)",), 3, 23, 23),
        (("rx",), 2, 8, 8),
        (("ii",), 2, 10, 10),
        (("rp",), 1, 6, 6),
    ),
    "dec": (
        (("r8",), 1, 4, 4),
        (("(hl)",), 1, 11, 11),
        (("(i+d)",), 3, 23, 23),
        (("rx",), 2, 8, 8),
        (("ii",), 2, 10, 10),
        (("rp",), 1, 6, 6),
    ),
    "im": ((("n",), 2, 8, 8),),
    "bit": (
        (("n", "r8"), 2, 8, 8),
        (("n", "(hl)"), 2, 12, 12),
        (("n", "(i+d)"), 4, 20, 20),
    ),
    "set": (
        (("n", "r8"), 2, 8, 8),
        (("n", "(hl)"), 2, 15, 15),
        (("n", "(i+d)"), 4, 23, 23),
        (("n", "(i+d)", "r8"), 4, 23, 23),  # undocumented
    ),
    "res": (
        (("n", "r8"), 2, 8, 8),
        (("n", "(hl)"), 2, 15, 15),
        (("n", "(i+d)"), 4, 23, 23),
        (("n", "(i+d)", "r8"), 4, 23, 23),  # undocumented
    ),
    "jp": (
        (("(hl)",), 1, 4, 4),
        (("(ii)",), 2, 8, 8),
        (("cc", "n"), 3, 10, 10),
        (("n",), 3, 10, 10),
    ),
    # A conditional relative jump costs 12T taken, 7T not taken.
    "jr": ((("cc", "n"), 2, 7, 12), (("n",), 2, 12, 12)),
    "djnz": ((("n",), 2, 8, 13),),  # 13T while B is non-zero, 8T on the pass that ends it
    "call": ((("cc", "n"), 3, 10, 17), (("n",), 3, 17, 17)),
    "ret": ((("cc",), 1, 5, 11), ((), 1, 10, 10)),
    "rst": ((("n",), 1, 11, 11),),
    "in": (
        (("a", "(nn)"), 2, 11, 11),
        (("r8|f", "(c)"), 2, 12, 12),
        (("(c)",), 2, 12, 12),
    ),
    "out": (
        (("(nn)", "a"), 2, 11, 11),
        (("(c)", "r8|n"), 2, 12, 12),
    ),
    **{name: _ROTATE_RULES for name in ("rlc", "rrc", "rl", "rr", "sla", "sra", "sll", "sli", "srl")},
}


def _matches(pattern: tuple[str, ...], operands: list[frozenset[str]]) -> bool:
    if len(pattern) != len(operands):
        return False
    return all(any(tag in tags for tag in slot.split("|")) for slot, tags in zip(pattern, operands))


def instruction_cost(mnemonic: str, operands: list[str]) -> tuple[int, int, int] | None:
    """``(bytes, T-min, T-max)`` for one instruction, or None if it isn't one."""
    name = mnemonic.lower()
    if name in _REPEATING_BLOCK and not operands:
        return _REPEATING_BLOCK[name]
    if name in _SIMPLE and not operands:
        size, t_states = _SIMPLE[name]
        return size, t_states, t_states
    rules = _TABLE.get(name)
    if rules is None:
        return None
    tags = [classify(operand) for operand in operands]
    for pattern, size, t_min, t_max in rules:
        if _matches(pattern, tags):
            return size, t_min, t_max
    return None


# --- directives --------------------------------------------------------------------------

# Directives that emit no bytes of their own. Listed rather than inferred so that anything
# *not* here is reported as unknown instead of silently counting as zero -- a meter that
# quietly ignores what it doesn't understand is worse than one that says so.
_NO_SIZE_DIRECTIVES = frozenset(
    {
        "org", "equ", "=", "defl", "include", "incdir", "device", "end", "assert", "display",
        "output", "page", "slot", "align", "macro", "endm", "mend", "endmacro", "rept", "endr",
        "dup", "edup", "module", "endmodule", "struct", "ends", "if", "ifdef", "ifndef", "ifn",
        "ifused", "else", "elseif", "endif", "define", "undefine", "export", "labelslist",
        "savesna", "savebin", "savetap", "savetrd", "savehob", "emptytrd", "emptytap", "cspectmap",
        "sldopt", "lua", "endlua", "shellexec", "opt", "abyte", "textarea", "encoding",
    }
)

_BYTE_DIRECTIVES = frozenset({"db", "defb", "dm", "defm", "byte", ".db", ".byte", "text"})
_WORD_DIRECTIVES = frozenset({"dw", "defw", "word", ".dw", ".word"})
_DWORD_DIRECTIVES = frozenset({"dd", "defd", "dword", ".dd"})
_SPACE_DIRECTIVES = frozenset({"ds", "defs", "block", ".ds", "rb"})


def parse_number(token: str) -> int | None:
    """A literal in any of the notations Z80 assemblers use, or None if it isn't one."""
    text = token.strip().lower().replace("_", "")
    if not text:
        return None
    try:
        if text.startswith("$") or text.startswith("#"):
            return int(text[1:], 16)
        if text.startswith("0x"):
            return int(text[2:], 16)
        if text.startswith("%"):
            return int(text[1:], 2)
        if text.startswith("0b") and set(text[2:]) <= {"0", "1"}:
            return int(text[2:], 2)
        if text.endswith("h"):
            return int(text[:-1], 16)
        if text.endswith("b") and set(text[:-1]) <= {"0", "1"}:
            return int(text[:-1], 2)
        return int(text, 10)
    except ValueError:
        return None


def _quoted_length(operand: str) -> int | None:
    """How many bytes a quoted literal emits, or None if the operand isn't one."""
    text = operand.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return len(text) - 2
    return None


def directive_bytes(mnemonic: str, operands: list[str]) -> int | None:
    """How many bytes a data directive emits, or None if it isn't a known directive.

    Returns 0 for the many directives that emit nothing (``org``, ``equ``, ``if`` ...) --
    those are known and cost nothing, which is a different answer from "not recognised".
    """
    name = mnemonic.lower()
    if name in _NO_SIZE_DIRECTIVES:
        return 0
    if name in _BYTE_DIRECTIVES:
        return sum(_quoted_length(operand) or 1 for operand in operands)
    if name in _WORD_DIRECTIVES:
        return 2 * len(operands)
    if name in _DWORD_DIRECTIVES:
        return 4 * len(operands)
    if name in _SPACE_DIRECTIVES:
        # `ds 32` reserves 32 bytes; `ds count*2` needs an expression evaluator we don't
        # have, so it counts as unknown rather than as zero.
        return parse_number(operands[0]) if operands else None
    return None


# --- source parsing ----------------------------------------------------------------------


def strip_comment(line: str) -> str:
    """Everything before the first ``;`` or ``//`` that isn't inside a quoted literal."""
    quote: str | None = None
    for index, char in enumerate(line):
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char == ";":
            return line[:index]
        elif char == "/" and line[index + 1 : index + 2] == "/":
            return line[:index]
    return line


def _split_top_level(text: str, separators: str) -> list[str]:
    """Split on ``separators``, ignoring any inside brackets or quotes."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    for char in text:
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            current.append(char)
        elif char in "([":
            depth += 1
            current.append(char)
        elif char in ")]":
            depth = max(0, depth - 1)
            current.append(char)
        elif char in separators and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _is_known(mnemonic: str) -> bool:
    name = mnemonic.lower()
    return (
        name in _TABLE
        or name in _SIMPLE
        or name in _REPEATING_BLOCK
        or name in _NO_SIZE_DIRECTIVES
        or name in _BYTE_DIRECTIVES
        or name in _WORD_DIRECTIVES
        or name in _DWORD_DIRECTIVES
        or name in _SPACE_DIRECTIVES
    )


def split_line(line: str) -> tuple[str | None, list[str]]:
    """One source line -> ``(label, statements)``, the label removed from the statements.

    Two label styles have to survive this. ``loop:`` is easy -- it is its own statement
    once the line is split on colons, and a lone word that isn't a mnemonic is a label.
    ``loop  ld a,1`` -- a bare name in column zero -- is harder, since nothing in the text
    marks it: the giveaway is that the line starts flush left *and* its first word is not
    a mnemonic, which is exactly the rule an assembler applies too. An indented line is
    never treated that way, so ``    ld a,1`` can't lose its ``ld``.

    The label is *returned* rather than dropped because it names things elsewhere: the
    memory map calls a region after the label that opens it (``asm_layout``). The meter
    itself only ever wanted the statements, so it takes the second half via ``_statements``
    -- one rule, two readers, no chance of the two disagreeing about what a label is.
    """
    body = strip_comment(line)
    stripped = body.strip()
    if not stripped:
        return None, []

    label: str | None = None
    parts = [part.strip() for part in _split_top_level(stripped, ":")]
    if len(parts) > 1 and parts[0] and " " not in parts[0] and (not _is_known(parts[0]) or _assigns(parts[1])):
        label = parts[0]
        parts = parts[1:]  # `loop:` and anything after it on the same line
    elif len(parts) == 1 and body[:1] not in (" ", "\t"):
        head, _, rest = stripped.partition(" ")
        if not _is_known(head) or _assigns(rest):
            label = head
            parts = [rest.strip()]  # a bare column-zero label; `name equ 5` keeps its `equ`
    return label, [part for part in parts if part]


def _assigns(text: str) -> bool:
    """Does what follows a name make it a *definition* -- ``equ``, ``defl``, ``=``?

    The tie-breaker for a name that also happens to be a directive. ``Text equ $8750``
    defines a constant called Text; without this it parses as the ``TEXT`` byte directive
    with one operand and costs a phantom byte. Real projects hit this -- a memory-map
    include full of ``Name equ $addr`` lines is exactly where names like Text, Screen and
    Align live, and an assembler reads all of them as labels because a name in front of
    ``equ`` can be nothing else.
    """
    head = text.strip().split(None, 1)[0].lower() if text.strip() else ""
    return head in ("equ", "defl", "=") or head.startswith("=")


def _statements(line: str) -> list[str]:
    """The statements on one source line, with any label removed -- see :func:`split_line`."""
    return split_line(line)[1]


def measure_statement(statement: str) -> MeterResult:
    """One statement (no label, no comment) -> its cost."""
    result = MeterResult()
    text = statement.strip()
    if not text:
        return result

    head = text.split(None, 1)
    mnemonic = head[0]
    operand_text = head[1] if len(head) > 1 else ""
    operands = [part.strip() for part in _split_top_level(operand_text, ",") if part.strip()]

    cost = instruction_cost(mnemonic, operands)
    if cost is not None:
        size, t_min, t_max = cost
        result.instructions = 1
        result.code_bytes = size
        result.t_states_min = t_min
        result.t_states_max = t_max
        return result

    emitted = directive_bytes(mnemonic, operands)
    if emitted is not None:
        result.data_bytes = emitted
        return result

    result.unknown = 1
    return result


def measure(text: str) -> MeterResult:
    """Measure a whole run of source -- an editor selection, or a file."""
    total = MeterResult()
    for line in text.splitlines():
        for statement in _statements(line):
            total.add(measure_statement(statement))
    return total


def format_result(result: MeterResult, timing: bool = True) -> str:
    """The one-line summary the meter shows. Timing leads, because timing is the question.

    ``timing=False`` drops the T-state total, which is what a *whole file* wants: summing
    every instruction in a file counts each one exactly once, and a file is loops and
    subroutines -- a routine called a hundred times contributes its cost once, a loop body
    contributes one iteration. That number answers no question anybody has. Size does:
    a file's byte total is what it occupies. So the file gets bytes, and a selection --
    a straight run you deliberately marked out -- gets the cycles it costs to execute.
    """
    if result.total_bytes == 0 and result.instructions == 0 and result.unknown == 0:
        return ""
    byte_word = "byte" if result.total_bytes == 1 else "bytes"
    parts = []
    if timing and result.instructions:
        parts.append("{}–{} T".format(result.t_states_min, result.t_states_max) if result.has_time_range else "{} T".format(result.t_states_min))
    parts.append("{} {}".format(result.total_bytes, byte_word))
    if result.instructions:
        parts.append("{} instr".format(result.instructions))
    if result.unknown:
        parts.append("{} unrecognised".format(result.unknown))
    return " · ".join(parts)
