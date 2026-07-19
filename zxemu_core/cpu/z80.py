"""Z80 CPU: registers plus a fetch/execute loop dispatching through per-prefix opcode tables."""

from __future__ import annotations

from .instructions import (
    BASE_TABLE,
    CB_TABLE,
    ED_TABLE,
    INDEXED_TABLE,
    execute_ddcb,
)
from .registers import Registers


def _signed8(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


class Z80:
    def __init__(self, memory) -> None:
        self.memory = memory
        self.regs = Registers()
        self.halted = False
        self.t_states = 0
        # Overridden by Machine/ULA wiring; default is the "nothing attached" floating-bus stub.
        self.io_read = lambda port: 0xFF
        self.io_write = lambda port, value: None
        # Active index register for the current DD/FD-prefixed instruction (set by _step_indexed).
        self._idx_pair = "ix"
        self._idx_hi = "ixh"
        self._idx_lo = "ixl"

    def reset(self) -> None:
        self.regs = Registers()
        self.regs.sp = 0xFFFF
        self.halted = False
        self.t_states = 0

    def add_t_states(self, count: int) -> None:
        self.t_states += count

    def read_opcode(self) -> int:
        """Fetch a byte via an M1 (opcode fetch) cycle: 4 T-states, increments R."""
        value = self.memory.read_byte(self.regs.pc)
        self.regs.pc = (self.regs.pc + 1) & 0xFFFF
        self.regs.r = (self.regs.r & 0x80) | ((self.regs.r + 1) & 0x7F)
        self.add_t_states(4)
        return value

    def fetch_byte(self) -> int:
        """Fetch an operand byte (immediate/displacement) at PC: 3 T-states, no R change."""
        value = self.memory.read_byte(self.regs.pc)
        self.regs.pc = (self.regs.pc + 1) & 0xFFFF
        self.add_t_states(3)
        return value

    def fetch_word(self) -> int:
        """Fetch a 16-bit little-endian immediate operand at PC: 6 T-states total."""
        lo = self.fetch_byte()
        hi = self.fetch_byte()
        return (hi << 8) | lo

    def read_mem(self, address: int) -> int:
        """Non-PC-relative memory read cycle (e.g. via (HL)/(nnnn)): 3 T-states."""
        value = self.memory.read_byte(address)
        self.add_t_states(3)
        return value

    def write_mem(self, address: int, value: int) -> None:
        """Non-PC-relative memory write cycle: 3 T-states."""
        self.memory.write_byte(address, value)
        self.add_t_states(3)

    def push_word(self, value: int) -> None:
        self.regs.sp = (self.regs.sp - 1) & 0xFFFF
        self.write_mem(self.regs.sp, (value >> 8) & 0xFF)
        self.regs.sp = (self.regs.sp - 1) & 0xFFFF
        self.write_mem(self.regs.sp, value & 0xFF)

    def pop_word(self) -> int:
        lo = self.read_mem(self.regs.sp)
        self.regs.sp = (self.regs.sp + 1) & 0xFFFF
        hi = self.read_mem(self.regs.sp)
        self.regs.sp = (self.regs.sp + 1) & 0xFFFF
        return (hi << 8) | lo

    def maskable_interrupt(self) -> int:
        """Service a maskable interrupt (IM 0 treated as IM 1, no external bus device).

        Returns T-states consumed (0 if IFF1 is disabled, i.e. masked)."""
        if not self.regs.iff1:
            return 0
        self.halted = False
        self.regs.iff1 = False
        self.regs.iff2 = False
        self.regs.r = (self.regs.r & 0x80) | ((self.regs.r + 1) & 0x7F)
        start = self.t_states
        if self.regs.im == 2:
            vector_addr = (self.regs.i << 8) | 0xFF
            lo = self.read_mem(vector_addr)
            hi = self.read_mem((vector_addr + 1) & 0xFFFF)
            target = (hi << 8) | lo
        else:
            target = 0x0038
        self.add_t_states(7)
        self.push_word(self.regs.pc)
        self.regs.pc = target
        return self.t_states - start

    def step(self) -> int:
        """Execute one instruction, returning the T-states it consumed."""
        start_t_states = self.t_states
        if self.halted:
            # While halted the CPU executes internal NOPs (refreshing R, burning
            # 4 T-states each) with PC parked just past the HALT, until an
            # interrupt clears self.halted. maskable_interrupt() then pushes that
            # already-past-the-HALT PC, so execution resumes correctly after it.
            self.regs.r = (self.regs.r & 0x80) | ((self.regs.r + 1) & 0x7F)
            self.add_t_states(4)
            return self.t_states - start_t_states
        opcode = self.read_opcode()
        if opcode == 0xCB:
            self._step_cb()
        elif opcode == 0xED:
            self._step_ed()
        elif opcode in (0xDD, 0xFD):
            self._step_indexed(opcode)
        else:
            handler = BASE_TABLE[opcode]
            if handler is None:
                raise NotImplementedError(f"opcode 0x{opcode:02X} not implemented")
            handler(self)
        return self.t_states - start_t_states

    def _step_cb(self) -> None:
        opcode = self.read_opcode()
        CB_TABLE[opcode](self)

    def _step_ed(self) -> None:
        opcode = self.read_opcode()
        ED_TABLE[opcode](self)

    def _step_indexed(self, prefix: int) -> None:
        # Prefix stacking (DD DD .., DD FD .., ...): only the last DD/FD before
        # a real opcode takes effect; earlier ones are wasted M1 fetches.
        while True:
            if prefix == 0xDD:
                self._idx_pair, self._idx_hi, self._idx_lo = "ix", "ixh", "ixl"
            else:
                self._idx_pair, self._idx_hi, self._idx_lo = "iy", "iyh", "iyl"
            opcode = self.read_opcode()
            if opcode in (0xDD, 0xFD):
                prefix = opcode
                continue
            break

        if opcode == 0xCB:
            displacement = _signed8(self.fetch_byte())
            sub_opcode = self.fetch_byte()  # DDCB/FDCB's final byte is a plain read, not M1
            execute_ddcb(self, displacement, sub_opcode)
            return
        if opcode == 0xED:
            # DD/FD immediately followed by ED: the index prefix is simply dropped/wasted.
            self._step_ed()
            return

        handler = INDEXED_TABLE.get(opcode)
        if handler is not None:
            handler(self)
            return
        base_handler = BASE_TABLE[opcode]
        if base_handler is None:
            raise NotImplementedError(f"opcode 0x{prefix:02X} 0x{opcode:02X} not implemented")
        base_handler(self)
