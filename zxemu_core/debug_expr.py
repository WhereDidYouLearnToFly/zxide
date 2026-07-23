"""Tiny expression language for conditional breakpoints: "stop only when A == $FF".

A plain breakpoint stops every time execution reaches an address. That is useless in
the place you most need it -- a routine called ten thousand times a frame, which
misbehaves on one of those calls. A condition turns "stop here" into "stop here *when
this is true*", which is the difference between finding the bug and pressing F5 all
afternoon.

The language is deliberately tiny, because a debugger condition is evaluated after
*every* instruction at that address: it has to be quick to type, quick to read back
in six months, and impossible to get subtly wrong.

    A == $FF                 a register against a value
    HL > $8000               16-bit registers work the same way
    (HL) == 0                parentheses read *memory* at that address
    ($5C08) != 0             ...including a literal address (here LAST-K)
    FZ == 1                  flags, as FS FZ FH FP FN FC
    B == 0 and C == 0        conditions joined with 'and' / 'or'

Values may be written `$FF` (hex, the Spectrum convention), `0xFF`, `%1010` (binary)
or plain decimal. Comparisons are `== != < <= > >=`.

What it deliberately is *not*: there is no arithmetic, no assignment, and no calls.
You cannot write `A + 1 == B`, and you cannot change machine state from a condition.
That keeps evaluation total -- any expression either yields true or false or fails to
parse when you enter it, and none of them can perturb the program you are debugging.
"""

from __future__ import annotations

import re

_REGISTERS_8 = ("a", "f", "b", "c", "d", "e", "h", "l", "i", "r")
_REGISTERS_16 = ("af", "bc", "de", "hl", "ix", "iy", "sp", "pc", "af2", "bc2", "de2", "hl2")
_FLAG_BITS = {"fs": 0x80, "fz": 0x40, "fh": 0x10, "fp": 0x04, "fn": 0x02, "fc": 0x01}

_COMPARISONS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
}
# Longest first, so "<=" is never mistaken for "<" followed by "=".
_COMPARISON_RE = re.compile(r"(==|!=|<=|>=|<|>)")


class ExpressionError(ValueError):
    """Raised when an expression can't be parsed. The message is shown to the user."""


def _parse_number(text: str) -> int | None:
    try:
        if text.startswith("$"):
            return int(text[1:], 16)
        if text.lower().startswith("0x"):
            return int(text[2:], 16)
        if text.startswith("%"):
            return int(text[1:], 2)
        return int(text, 10)
    except ValueError:
        return None


def _evaluate_operand(text: str, machine) -> int:
    """Resolve one side of a comparison to a number."""
    text = text.strip()
    if not text:
        raise ExpressionError("missing value")

    # (something) reads memory at that address -- (HL) or ($5C08).
    if text.startswith("(") and text.endswith(")"):
        address = _evaluate_operand(text[1:-1], machine)
        return machine.memory.read_byte(address & 0xFFFF)

    lowered = text.lower().replace("'", "2")  # HL' is stored as hl2
    if lowered in _FLAG_BITS:
        return 1 if machine.cpu.regs.f & _FLAG_BITS[lowered] else 0
    if lowered in _REGISTERS_8 or lowered in _REGISTERS_16:
        return getattr(machine.cpu.regs, lowered)

    number = _parse_number(text)
    if number is None:
        raise ExpressionError(f"don't understand {text!r}")
    return number


def _evaluate_comparison(text: str, machine) -> bool:
    match = _COMPARISON_RE.search(text)
    if match is None:
        raise ExpressionError(f"no comparison in {text.strip()!r} (expected ==, !=, <, <=, >, >=)")
    left = _evaluate_operand(text[: match.start()], machine)
    right = _evaluate_operand(text[match.end():], machine)
    return _COMPARISONS[match.group(1)](left, right)


def evaluate(expression: str, machine) -> bool:
    """Evaluate a condition against a machine's live state.

    'or' binds loosest, then 'and' -- the conventional precedence, so
    ``A == 1 and B == 2 or C == 3`` reads as ``(A == 1 and B == 2) or (C == 3)``.
    """
    for alternative in re.split(r"\bor\b", expression, flags=re.IGNORECASE):
        parts = re.split(r"\band\b", alternative, flags=re.IGNORECASE)
        if all(_evaluate_comparison(part, machine) for part in parts):
            return True
    return False


def validate(expression: str, machine) -> None:
    """Raise ExpressionError if the expression won't parse -- called when it's entered.

    Evaluated against the live machine, so a typo is reported at the moment you type
    it rather than silently never matching once the program is running.
    """
    evaluate(expression, machine)
