"""Spectrum48 machine: wires the CPU, memory, and ULA together and drives frame execution."""

from __future__ import annotations

from .cpu.z80 import Z80
from .keyboard import Keyboard
from .memory import Memory, create_48k_memory
from .ula import FRAME_TSTATES, Ula


class Machine:
    """A 48K Spectrum: CPU + paged memory + ULA (border/keyboard) wired together."""

    def __init__(self, rom_data: bytes):
        self.memory: Memory = create_48k_memory(rom_data)
        self.cpu = Z80(self.memory)
        self.keyboard = Keyboard()
        self.ula = Ula(keyboard=self.keyboard)
        self.cpu.io_read = self._io_read
        self.cpu.io_write = self._io_write
        self.frame_t_state = 0
        self.reset()

    def reset(self) -> None:
        self.cpu.reset()
        self.cpu.regs.im = 1  # matches the 48K ROM's own startup sequence, harmless before it runs
        self.frame_t_state = 0

    def _io_read(self, port: int) -> int:
        return self.ula.read_port(port)

    def _io_write(self, port: int, value: int) -> None:
        self.ula.write_port(port, value)

    def run_frame(self) -> None:
        """Execute one 50Hz frame's worth of T-states (69888), firing one interrupt at the start.

        Contention stalls (see ula.contention_delay) aren't applied to
        individual memory accesses yet -- this milestone targets functional
        correctness (boots the ROM, runs BASIC) rather than cycle-accurate
        timing; contention-sensitive raster effects are a later refinement.
        """
        self.cpu.maskable_interrupt()
        target = self.frame_t_state + FRAME_TSTATES
        while self.frame_t_state < target:
            self.frame_t_state += self.cpu.step()
        self.frame_t_state -= FRAME_TSTATES
