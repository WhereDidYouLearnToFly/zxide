"""What a Z80 instruction does, in one line -- the text behind the editor's hover help.

The point of this module is the *first* line of an explanation, not a manual. Hovering
``djnz`` should answer "decrement B and jump while it isn't zero, 13 T taken / 8 not"
without leaving the editor; anyone who then wants the full truth about flag behaviour in
undocumented cases is going to open a reference book anyway, and no tooltip competes with
that.

It pairs with :mod:`zxemu_core.debug.asm_meter`, which already holds the operand tables
and the timings. That is the reuse worth having: the meter can price the *exact* operand
form under the cursor (``ld a,(hl)`` is 7 T, ``ld a,(ix+d)`` is 19 T), so hover help shows
the cost of the instruction you actually wrote instead of a range covering every form.
This module adds only what the meter has no reason to know: what the instruction is *for*
and which flags it disturbs.

Flag notes are deliberately coarse -- "S Z H P/V N C" naming which flags change, not the
condition each one changes under. The detail belongs in a reference; the tooltip's job is
to stop you assuming a flag survived an instruction when it didn't.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from zxemu_core.debug import asm_meter, asm_symbols

_NO_FLAGS = "unaffected"
_MAX_SYMBOLS = 6  # a line naming more constants than this is better read than hovered

# mnemonic -> (what it does, which flags it disturbs)
_INSTRUCTIONS: dict[str, tuple[str, str]] = {
    "ld": ("Copy a value from the source (right) to the destination (left).", _NO_FLAGS),
    "push": ("Push a 16-bit register pair onto the stack; SP drops by 2.", _NO_FLAGS),
    "pop": ("Pull 16 bits off the stack into a register pair; SP rises by 2.", "only when popping AF, which restores them wholesale"),
    "ex": ("Swap two registers -- DE with HL, AF with its shadow, or HL with the word on top of the stack.", "only ex af,af', which swaps them out"),
    "exx": ("Swap BC, DE and HL with their shadow copies in one instruction.", _NO_FLAGS),
    "add": ("Add to A, or to a 16-bit register pair.", "S Z H P/V N C (16-bit adds change only H, N, C)"),
    "adc": ("Add with carry: source + carry flag, so 16-bit sums chain across bytes.", "S Z H P/V N C"),
    "sub": ("Subtract from A.", "S Z H P/V N C"),
    "sbc": ("Subtract with borrow: source + carry, the counterpart of adc for wide values.", "S Z H P/V N C"),
    "and": ("Bitwise AND with A -- clears every bit the operand doesn't have set.", "S Z P/V; H set, N and C cleared"),
    "or": ("Bitwise OR with A -- sets every bit the operand has set.", "S Z P/V; H, N, C cleared"),
    "xor": ("Bitwise XOR with A. `xor a` is the one-byte way to clear A and set Z.", "S Z P/V; H, N, C cleared"),
    "cp": ("Compare with A: subtracts without storing, so only the flags change.", "S Z H P/V N C"),
    "inc": ("Add one. 8-bit forms set flags; 16-bit forms touch none, which is why loop counters often live in a byte.", "8-bit: S Z H P/V N. 16-bit: unaffected"),
    "dec": ("Subtract one. Same split as inc: only the 8-bit forms report anything.", "8-bit: S Z H P/V N. 16-bit: unaffected"),
    "neg": ("Negate A (0 - A), i.e. two's complement.", "S Z H P/V N C"),
    "cpl": ("Invert every bit of A (one's complement).", "H and N set"),
    "daa": ("Fix A up after adding or subtracting packed BCD digits.", "S Z H P/V C"),
    "scf": ("Set the carry flag.", "C set; H and N cleared"),
    "ccf": ("Flip the carry flag.", "C inverted; H takes the old C, N cleared"),
    "rlca": ("Rotate A left; bit 7 wraps to bit 0 and into carry.", "C; H and N cleared"),
    "rrca": ("Rotate A right; bit 0 wraps to bit 7 and into carry.", "C; H and N cleared"),
    "rla": ("Rotate A left through carry -- 9-bit rotation, carry is the extra bit.", "C; H and N cleared"),
    "rra": ("Rotate A right through carry.", "C; H and N cleared"),
    "rlc": ("Rotate left; bit 7 wraps round to bit 0 and into carry.", "S Z P/V C; H and N cleared"),
    "rrc": ("Rotate right; bit 0 wraps round to bit 7 and into carry.", "S Z P/V C; H and N cleared"),
    "rl": ("Rotate left through carry.", "S Z P/V C; H and N cleared"),
    "rr": ("Rotate right through carry.", "S Z P/V C; H and N cleared"),
    "sla": ("Shift left, feeding in a zero -- a doubling.", "S Z P/V C; H and N cleared"),
    "sra": ("Shift right keeping bit 7 -- a signed halving.", "S Z P/V C; H and N cleared"),
    "srl": ("Shift right, feeding in a zero -- an unsigned halving.", "S Z P/V C; H and N cleared"),
    "sll": ("Undocumented: shift left feeding in a one. Assembles, but no two Z80 clones are guaranteed to agree.", "S Z P/V C; H and N cleared"),
    "sli": ("Undocumented: another name for sll.", "S Z P/V C; H and N cleared"),
    "rld": ("Rotate a BCD digit left between A and the byte at (HL).", "S Z P/V; H and N cleared"),
    "rrd": ("Rotate a BCD digit right between A and the byte at (HL).", "S Z P/V; H and N cleared"),
    "bit": ("Test one bit and report it in Z -- nothing is stored.", "S Z P/V; H set, N cleared"),
    "set": ("Set one bit of a register or memory byte.", _NO_FLAGS),
    "res": ("Clear one bit of a register or memory byte.", _NO_FLAGS),
    "jp": ("Jump to an address, optionally on a condition. Absolute, so it reaches anywhere.", _NO_FLAGS),
    "jr": ("Relative jump, -126..+129 from here. One byte shorter than jp, and slower when taken.", _NO_FLAGS),
    "djnz": ("Decrement B and jump while it is non-zero -- the Z80's built-in loop. B=0 means 256 passes.", _NO_FLAGS),
    "call": ("Push the return address and jump to a subroutine.", _NO_FLAGS),
    "ret": ("Return: pop an address off the stack and jump to it.", _NO_FLAGS),
    "reti": ("Return from a maskable interrupt (tells peripherals the service routine has finished).", _NO_FLAGS),
    "retn": ("Return from NMI, restoring the interrupt-enable state saved when it fired.", _NO_FLAGS),
    "rst": ("Call a fixed low address ($00, $08 ... $38) in one byte.", _NO_FLAGS),
    "halt": ("Stop and wait for an interrupt. Nothing else releases it -- with interrupts disabled the CPU stays here.", _NO_FLAGS),
    "nop": ("Do nothing for 4 T-states.", _NO_FLAGS),
    "di": ("Disable maskable interrupts.", _NO_FLAGS),
    "ei": ("Enable maskable interrupts -- from *after* the next instruction, so `ei; halt` cannot miss one.", _NO_FLAGS),
    "im": ("Choose interrupt mode 0, 1 (jump to $0038) or 2 (vector table via register I).", _NO_FLAGS),
    "in": ("Read a byte from an I/O port.", "the `in r,(c)` forms set S Z P/V; `in a,(n)` sets none"),
    "out": ("Write a byte to an I/O port. On a Spectrum, port $FE is border, speaker and tape.", _NO_FLAGS),
    "ldi": ("Copy one byte (HL)->(DE), then advance both and decrement BC.", "P/V holds 'BC is still non-zero'; H and N cleared"),
    "ldd": ("Copy one byte (HL)->(DE), then step both back and decrement BC.", "P/V holds 'BC is still non-zero'; H and N cleared"),
    "ldir": ("Block copy (HL)->(DE), BC times, upwards. 21 T per byte, 16 on the last.", "cleared on exit"),
    "lddr": ("Block copy downwards -- the direction to use when the areas overlap the other way.", "cleared on exit"),
    "cpi": ("Compare A with (HL), then advance HL and decrement BC.", "S Z H P/V; N set; C untouched"),
    "cpd": ("Compare A with (HL), then step HL back and decrement BC.", "S Z H P/V; N set; C untouched"),
    "cpir": ("Search upwards for A, stopping on a match or when BC runs out.", "S Z H P/V; N set; C untouched"),
    "cpdr": ("Search downwards for A.", "S Z H P/V; N set; C untouched"),
    "ini": ("Read a port into (HL), advance HL, decrement B.", "Z reflects B; N set"),
    "ind": ("Read a port into (HL), step HL back, decrement B.", "Z reflects B; N set"),
    "inir": ("Block read from a port into memory, B times.", "Z set, N set on exit"),
    "indr": ("Block read downwards from a port into memory.", "Z set, N set on exit"),
    "outi": ("Write (HL) to a port, advance HL, decrement B.", "Z reflects B; N set"),
    "outd": ("Write (HL) to a port, step HL back, decrement B.", "Z reflects B; N set"),
    "otir": ("Block write from memory to a port, B times.", "Z set, N set on exit"),
    "otdr": ("Block write downwards from memory to a port.", "Z set, N set on exit"),
}

# Assembler directives are not instructions and cost no time, but they are what a beginner
# is most likely to be unsure about, so they get the same treatment.
_DIRECTIVES: dict[str, str] = {
    "org": "Assemble the following code at this address.",
    "equ": "Give a name a constant value. Costs no bytes -- it exists only at assembly time.",
    "db": "Emit bytes literally (also defb / dm / defm; strings are allowed).",
    "defb": "Emit bytes literally.",
    "dm": "Emit a string as bytes.",
    "defm": "Emit a string as bytes.",
    "dw": "Emit 16-bit words, low byte first.",
    "defw": "Emit 16-bit words, low byte first.",
    "ds": "Reserve a block of bytes (filled with zero unless told otherwise).",
    "defs": "Reserve a block of bytes.",
    "include": "Assemble another source file here.",
    "incbin": "Embed a binary file's bytes here -- how assets get into the program.",
    "device": "Choose the target machine, which is what makes savesna/savetap possible.",
    "savesna": "Write a .sna snapshot of the assembled memory, with a start address.",
    "savetap": "Write a .tap tape image of the assembled memory.",
    "savebin": "Write a raw binary of an address range.",
    "align": "Advance to the next address that is a multiple of the given power of two.",
    "macro": "Begin a macro definition; endm ends it.",
    "endm": "End a macro definition.",
    "module": "Prefix the labels that follow with a module name.",
    "endmodule": "End the module's label prefix.",
    "endmod": "End the module's label prefix (short form of endmodule).",
    "dup": "Repeat the block that follows N times (edup ends it).",
    "edup": "End a dup block.",
    "rept": "Repeat the block that follows N times (endr ends it).",
    "endr": "End a rept block.",
    "if": "Assemble the block that follows only if the expression is true.",
    "ifdef": "Assemble the block only if the symbol is defined.",
    "ifndef": "Assemble the block only if the symbol is not defined.",
    "else": "The alternative branch of a conditional assembly block.",
    "endif": "End a conditional assembly block.",
    "page": "Select the memory page the following code is assembled into.",
    "slot": "Select the 16K slot that page directives apply to.",
    "lua": "Begin a Lua block run at assembly time; endlua ends it.",
    "endlua": "End a Lua block.",
    "display": "Print a value in the assembler's output while assembling.",
    "assert": "Fail the build if the expression is not true.",
}


@dataclass
class Help:
    """One instruction's hover text: what it is, what it costs, what it disturbs."""

    title: str          # the instruction as written, e.g. "ld a,(hl)"
    summary: str        # one line: what it does
    cost: str = ""      # "1 byte · 7 T", empty when the form isn't priceable
    flags: str = ""     # which flags change, empty for directives
    symbols: list[str] = field(default_factory=list)  # "SCREEN = 16384 ($4000)" per constant

    def as_text(self) -> str:
        """Plain text, one fact per line -- what the tooltip shows."""
        lines = [self.title]
        if self.summary:  # a line that only names constants has nothing to explain
            lines.append(self.summary)
        if self.cost:
            lines.append(self.cost)
        if self.flags:
            lines.append("Flags: {}".format(self.flags))
        lines.extend(self.symbols)
        return "\n".join(lines)


def _cost_text(mnemonic: str, operands: list[str]) -> str:
    """Price this exact operand form through the meter's tables, or return nothing."""
    cost = asm_meter.instruction_cost(mnemonic, operands)
    if cost is None:
        return ""
    size, t_min, t_max = cost
    timing = "{}–{} T".format(t_min, t_max) if t_min != t_max else "{} T".format(t_min)
    return "{} {} · {}".format(size, "byte" if size == 1 else "bytes", timing)


def _statement_at(line: str, column: int) -> tuple[str, list[str], str] | None:
    """The instruction on this line, as (mnemonic, operands), label and comment removed.

    Hovering anywhere on the line answers about that line's instruction -- hovering the
    ``(hl)`` in ``ld a,(hl)`` asks the same question as hovering the ``ld``, and having
    only the mnemonic respond would feel broken rather than precise.
    """
    body = asm_meter.strip_comment(line)
    if not body.strip() or column > len(line):
        return None
    for part in body.split(":"):
        text = part.strip()
        if not text:
            continue
        head = text.split(None, 1)
        mnemonic = head[0].lower()
        if mnemonic not in _INSTRUCTIONS and mnemonic not in _DIRECTIVES:
            continue  # a label, or something we have nothing to say about
        operand_text = head[1] if len(head) > 1 else ""
        operands = [operand.strip() for operand in operand_text.split(",") if operand.strip()]
        return mnemonic, operands, " ".join(text.split())
    return None


def _constant_text(constant: asm_symbols.Constant) -> str:
    """One constant as a tooltip line: what it is worth, and where it was set.

    The working is shown when the definition isn't already a plain number
    (``TILE_END = TILES+2048 = 34816 ($8800)``), because the interesting part of a derived
    constant is usually what it was derived from -- but repeating ``= 4`` for ``equ 4``
    would be noise.
    """
    if constant.value is None:
        text = "{} = {}".format(constant.name, " ".join(constant.expression.split()))
    else:
        shown = "{} (${:04X})".format(constant.value, constant.value) if 0 <= constant.value <= 0xFFFF else str(constant.value)
        if asm_meter.parse_number(constant.expression) is None:
            text = "{} = {} = {}".format(constant.name, " ".join(constant.expression.split()), shown)
        else:
            text = "{} = {}".format(constant.name, shown)
    return "{} · {}".format(text, constant.origin) if constant.origin else text


def describe(line: str, column: int = 0, symbols: dict[str, asm_symbols.Constant] | None = None) -> Help | None:
    """Hover help for the instruction on ``line``, or None if there is nothing to say.

    ``symbols`` is the ``equ`` table of the file being edited (see
    :mod:`zxemu_core.debug.asm_symbols`). Any constant the line names is appended to the
    instruction's help rather than replacing it -- hovering ``ld hl,SCREEN`` raises both
    questions at once -- and a line that names a constant but holds no instruction still
    gets a tooltip, since the value is the whole answer there.
    """
    found = _statement_at(line, column)
    constants = [_constant_text(constant) for constant in asm_symbols.references(line, symbols)[:_MAX_SYMBOLS]]
    if found is None:
        if not constants:
            return None
        return Help(title=" ".join(asm_meter.strip_comment(line).split()), summary="", symbols=constants)
    mnemonic, operands, written = found  # the title is the statement as you typed it
    if mnemonic in _INSTRUCTIONS:
        summary, flags = _INSTRUCTIONS[mnemonic]
        return Help(title=written, summary=summary, cost=_cost_text(mnemonic, operands), flags=flags, symbols=constants)
    return Help(title=written, summary=_DIRECTIVES[mnemonic], symbols=constants)
