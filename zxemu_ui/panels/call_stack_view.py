"""CallStackView -- reconstruct "who called whom" from the stack, while paused.

The Z80 has no call-stack structure. `CALL` pushes a two-byte return address and
`RET` pops one; nothing marks a frame, records a caller, or distinguishes a return
address from any other word the program happened to push. So a call stack cannot be
*read* -- it has to be *inferred*.

How the inference works
-----------------------
Walk up from SP a word at a time. For each word, ask: could this be a return
address? It could, if the bytes immediately *before* it are a call instruction that
would have pushed exactly it:

    * three bytes back: ``CALL nn`` (0xCD) or a conditional ``CALL cc,nn``, whose
      operand is where we'd have ended up, or
    * one byte back: an ``RST`` (which pushes the address after the single opcode).

A word that passes is very likely a genuine frame; a word that fails is data the
program pushed (registers, locals) and is skipped.

Why this is a heuristic, and why that's fine
--------------------------------------------
It can be fooled both ways. Data that happens to sit just after something that looks
like a CALL will be reported as a frame (a false positive), and a routine that
manipulates its own return address -- a jump table that pushes a target and RETs to
it, a common Z80 idiom -- won't look like a call at all (a false negative).

The two tests are not equally trustworthy, which is worth knowing when you read the
panel. A CALL match cross-checks its **16-bit operand** against the address we would
have returned to, so a false positive needs a 1-in-65536 coincidence -- those frames
are as good as certain. An RST match can only check **one byte**, so it is roughly
256 times weaker evidence. See the RST opcode list below for what that forced.

The alternative is to record every CALL and RET as it executes, which is exact but
only works while you are stepping, and gives nothing at all if you attach to an
already-running program. Since this view's job is to answer "how did I get here?"
the moment you hit a breakpoint, inference wins: it works immediately, costs nothing
while running, and is right nearly always. Entries are marked so you can see the
evidence rather than having to trust it.
"""

from __future__ import annotations

from PyQt5.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from zxemu_core.debug import rom_symbols
from zxemu_ui.theme import monospace_font

MAX_FRAMES = 16      # how many plausible frames to report
MAX_STACK_WORDS = 256  # how far up the stack to look before giving up

_CALL_CONDITIONAL = frozenset({0xC4, 0xCC, 0xD4, 0xDC, 0xE4, 0xEC, 0xF4, 0xFC})

# RST opcodes, *excluding* 0xFF (RST $38). Two reasons, and they compound:
#
#   * $FF is the most common filler byte there is -- ROM font data is full of it -- so
#     any stack word preceded by one looks like an RST frame. Measured against the real
#     48K ROM, keeping it turned 3 genuine frames into 14, i.e. 11 false positives.
#   * $0038 is the IM 1 interrupt vector, and an interrupt does *not* execute an RST:
#     the CPU pushes PC and jumps there itself. So a return address pushed by an
#     interrupt has no call instruction before it and is undetectable by this method
#     anyway -- excluding RST $38 costs us nothing real.
#
# The other RSTs stay: RST $10 (PRINT-A) in particular is everyday Spectrum code.
_RST_OPCODES = frozenset({0xC7, 0xCF, 0xD7, 0xDF, 0xE7, 0xEF, 0xF7})


def _call_site(memory, return_address: int):
    """If ``return_address`` looks like it was pushed by a call, describe that call.

    Returns (call_address, description) or None. See the module docstring for why
    this is a plausibility test rather than a lookup.
    """
    three_back = (return_address - 3) & 0xFFFF
    opcode = memory.read_byte(three_back)
    if opcode == 0xCD or opcode in _CALL_CONDITIONAL:
        target = memory.read_byte((three_back + 1) & 0xFFFF) | (
            memory.read_byte((three_back + 2) & 0xFFFF) << 8
        )
        mnemonic = "call" if opcode == 0xCD else "call cc"
        return three_back, f"{mnemonic} ${target:04X}"

    one_back = (return_address - 1) & 0xFFFF
    opcode = memory.read_byte(one_back)
    if opcode in _RST_OPCODES:
        return one_back, f"rst ${opcode - 0xC7:02X}"
    return None


def call_frames(memory, sp: int, pc: int, max_frames: int = MAX_FRAMES) -> list[tuple]:
    """Infer the call stack as a list of (stack_addr, return_addr, call_addr, description)."""
    frames = []
    for step in range(MAX_STACK_WORDS):
        if len(frames) >= max_frames:
            break
        address = (sp + step * 2) & 0xFFFF
        word = memory.read_byte(address) | (memory.read_byte((address + 1) & 0xFFFF) << 8)
        site = _call_site(memory, word)
        if site is not None:
            call_address, description = site
            frames.append((address, word, call_address, description))
    return frames


class CallStackView(QWidget):
    """Shows the inferred chain of callers, innermost first. Only meaningful while paused."""

    def __init__(self, machine, parent=None):
        super().__init__(parent)
        self.machine = machine

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._text.setFont(monospace_font())
        root.addWidget(self._text, 1)

        self.refresh(force=True)

    def refresh(self, frame_count: int | None = None, force: bool = False) -> None:
        if not force and not self.isVisible():
            return
        cpu = self.machine.cpu
        pc, sp = cpu.regs.pc, cpu.regs.sp
        label_roms = self.machine.rom_symbols_valid()
        # Not name_for: while stepping, PC is usually *inside* a routine rather than at
        # its entry point, and "which routine am I in" is the question being asked.
        inside = rom_symbols.enclosing(pc) if label_roms else None
        here = f"  in {inside[0]}+${inside[1]:02X}" if inside else ""
        lines = [f"  PC ${pc:04X}   (current){here}"]
        for stack_addr, return_addr, call_addr, description in call_frames(
            self.machine.memory, sp, pc
        ):
            described = rom_symbols.annotate(description, label_roms)
            lines.append(
                f"  ${return_addr:04X} <- ${call_addr:04X}  {described:<14} [sp+${stack_addr - sp:02X}]"
            )
        if len(lines) == 1:
            lines.append("  (no plausible return addresses on the stack)")
        self._text.setPlainText("\n".join(lines))

    def set_mono_scale(self, scale: float) -> None:
        self._text.setFont(monospace_font(scale))
