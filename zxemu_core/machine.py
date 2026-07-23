"""Spectrum machines: wire CPU + paged memory + ULA + sound together and run frames.

``Machine`` is the 48K; ``Machine128`` (below) extends it with the 128K's bank
paging (port 0x7FFD) and AY sound chip. The 48K wiring is factored into ``_wire()``
so the 128K subclass can build a different memory map first and then reuse the exact
same CPU/ULA/sound plumbing.

The machine is also where the pieces that need a *whole* Spectrum live, because no
single chip owns them:

  * **audio timestamps** -- the ULA records the speaker bit, but only the machine
    knows the frame clock, so it is the machine that timestamps each flip,
  * **the tape trap** -- fast tape loading means intercepting the ROM at a specific
    address, which needs the CPU and the memory map together (see ``_tape_trap``).
"""

from __future__ import annotations

from typing import NamedTuple

from . import tape
from .ay import AY8912
from .beeper import Beeper
from .mixer import SoundMixer
from .cpu.z80 import Z80
from .keyboard import Keyboard
from .memory import Memory, create_48k_memory, create_128k_memory
from .ula import FRAME_TSTATES, FRAME_TSTATES_128K, Ula

# The trap replaces the whole (real-time) LD-BYTES routine, so its exact T-state cost is
# fictional; we bill a token amount just to advance the frame clock past the "instruction".
TAPE_TRAP_TSTATES = 16


class Machine:
    """A 48K Spectrum: CPU + paged memory + ULA (border/keyboard) + beeper wired together."""

    def __init__(self, rom_data: bytes):
        self.memory: Memory = create_48k_memory(rom_data)
        self._wire()

    def _wire(self) -> None:
        """Attach the CPU, ULA, keyboard and sound to ``self.memory`` and reset.

        Everything here is machine-model-independent -- it works against whatever
        memory map the caller built -- which is why ``Machine128`` calls it too
        instead of duplicating the wiring.
        """
        self.cpu = Z80(self.memory)
        self.keyboard = Keyboard()
        self.ula = Ula(keyboard=self.keyboard)
        # Audio pipeline: a mixer fed by one or more sound sources. The 48K has just
        # the beeper; Machine128 adds the AY. It stays dormant (no samples, no cost)
        # until a UI layer switches ``audio.enabled`` on.
        self.beeper = Beeper()
        self.audio = SoundMixer(sample_rate=self.beeper.sample_rate)
        self.audio.add_source(self.beeper)
        self._speaker_level = 0  # last speaker bit we handed to the beeper
        self.frame_tstates = FRAME_TSTATES  # per-model frame length (128K overrides)
        self.cpu.io_read = self._io_read
        self.cpu.io_write = self._io_write
        self.frame_t_state = 0
        # Tape: a TapeDeck when a .tap is inserted, else None. Fast loading is on by
        # default; the trap below only acts when a tape is present, so it's inert until
        # then. Both models get this identically (the 48K and 128K share LD-BYTES).
        self.tape: tape.TapeDeck | None = None
        self.fast_load_enabled = True
        self.cpu.set_trap(tape.LD_BYTES_ENTRY, self._tape_trap)
        self.reset()

    def reset(self) -> None:
        self.cpu.reset()
        self.cpu.regs.im = 1  # matches the 48K ROM's own startup sequence, harmless before it runs
        self.frame_t_state = 0

    # --- display / paging hooks (overridden by Machine128) --------------------

    def display_memory(self):
        """The raw 16K bank the ULA rasterises. On 48K the screen is always slot 1."""
        return self.memory.slots[1].data

    def paging_state(self):
        """Live 0x7FFD paging state for the memory-map view; None means 'unpaged' (48K)."""
        return None

    # --- tape -----------------------------------------------------------------

    def insert_tape(self, deck: tape.TapeDeck | None) -> None:
        """Put a tape in the deck (or None to eject); rewound to its first block."""
        self.tape = deck
        if deck is not None:
            deck.rewind()

    def eject_tape(self) -> None:
        self.tape = None

    def _tape_trap(self):
        """CPU trap at LD-BYTES: fast-load the next block, or decline (return None).

        Declines -- letting the ROM run the routine for real -- when there's no tape or
        fast loading is off. It also verifies the bytes at the trap address really are
        LD-BYTES (``INC D`` / ``EX AF,AF'``): on the 128K that is only true while the
        48-BASIC ROM is paged, so the trap never misfires inside the 128 menu ROM, and
        on the 48K it is a cheap sanity guard. Returns the billed T-states when it acts.
        """
        if self.tape is None or not self.fast_load_enabled:
            return None
        if self.memory.read_byte(0x0556) != 0x14 or self.memory.read_byte(0x0557) != 0x08:
            return None  # not the real LD-BYTES (wrong ROM paged) -- don't intercept
        return TAPE_TRAP_TSTATES if tape.fast_load(self, self.tape) else None

    # --- IO + frame loop ------------------------------------------------------

    def _io_read(self, port: int) -> int:
        return self.ula.read_port(port)

    def _io_write(self, port: int, value: int) -> None:
        self.ula.write_port(port, value)
        # Timestamp speaker flips for the beeper. frame_t_state is the clock at the
        # start of the current instruction (its T-states are added after step()
        # returns), so the flip is placed a few T-states early -- inaudible for the
        # beeper, and it keeps the audio timing entirely inside the Machine.
        if self.beeper.enabled and self.ula.speaker != self._speaker_level:
            self._speaker_level = self.ula.speaker
            self.beeper.set_level(self.frame_t_state, self._speaker_level)

    def run_frame(self) -> None:
        """Execute one 50Hz frame's worth of T-states, firing one interrupt at the start.

        The frame length is ``self.frame_tstates`` (69888 on 48K, 70908 on 128K).
        Contention stalls (see ula.contention_delay) aren't applied to individual
        memory accesses yet -- this milestone targets functional correctness (boots
        the ROM, runs BASIC) rather than cycle-accurate timing; contention-sensitive
        raster effects are a later refinement.
        """
        self.cpu.maskable_interrupt()
        # Run *up to* the frame length, not up to "wherever we started plus a frame":
        # the target has to be absolute so the carried remainder is consumed by this
        # frame instead of being added to again. Getting that wrong lets the remainder
        # accumulate the overshoot of every frame forever, and since flips are
        # timestamped with this same clock, the tail of each frame eventually lands
        # past frame_tstates -- where the beeper clamps it -- silently destroying a
        # growing slice of the waveform.
        while self.frame_t_state < self.frame_tstates:
            self.frame_t_state += self.cpu.step()
        # Carry the sub-frame remainder so the average frame length stays exact. Block
        # instructions run one iteration per step() (see blockio.py), so a single step
        # never overshoots by more than a few T-states -- the remainder stays small and
        # audio timestamps stay in-frame.
        self.frame_t_state -= self.frame_tstates
        # Close out the frame's audio: resample the sound sources' activity gathered
        # above into PCM the UI can play. A no-op while audio is disabled.
        self.audio.end_frame(self.frame_tstates)


class Paging128(NamedTuple):
    """A snapshot of the 128K's live 0x7FFD paging state, for the memory-map view."""

    port_7ffd: int      # the raw latch value
    rom_index: int      # 0 (128 editor) or 1 (48 BASIC), in slot 0
    ram_bank: int       # which RAM bank (0-7) sits in slot 3
    screen_bank: int    # which RAM bank the ULA displays: 5 (normal) or 7 (shadow)
    locked: bool        # paging disabled until reset (bit 5 was set)
    slot_labels: tuple  # human labels per slot, e.g. ("ROM0", "RAM5", "RAM2", "RAM0")


class Machine128(Machine):
    """A 128K Spectrum: the 48K wiring plus bank paging (port 0x7FFD) and the AY chip.

    The memory is a *pool* of eight RAM banks and two ROMs; port 0x7FFD swaps a ROM
    into slot 0 and a RAM bank into slot 3, and selects which bank the ULA displays.
    The base ``Machine`` supplies everything else unchanged -- we only override memory
    construction, the IO decode (to add 0x7FFD and the AY ports), the frame length,
    the display/paging hooks, and reset.
    """

    def __init__(self, rom0_data: bytes, rom1_data: bytes):
        self.memory, self.rom_banks, self.ram_banks = create_128k_memory(rom0_data, rom1_data)
        self.port_7ffd = 0
        self._locked = False
        self._wire()  # cpu/ula/keyboard/beeper/mixer + reset (see base Machine)
        self.frame_tstates = FRAME_TSTATES_128K
        # The AY joins the beeper in the mixer, so both play through one stream.
        self.ay = AY8912(sample_rate=self.beeper.sample_rate)
        self.audio.add_source(self.ay)

    def reset(self) -> None:
        super().reset()
        # A real 128K powers up unlocked with ROM0 selected and the standard map.
        self.set_paging(0, force=True)

    def set_paging(self, value: int, force: bool = False) -> None:
        """Apply a 0x7FFD byte: page ROM into slot 0 and a RAM bank into slot 3.

        Once the lock bit (bit 5) latches, further writes from the CPU are ignored
        until reset -- the write that *sets* the lock still takes effect first. The
        snapshot loader passes ``force=True`` so it can restore an already-locked
        state. Slots 1 and 2 (RAM5, RAM2) never move; the screen-bank select (bit 3)
        changes only what the ULA displays, handled in ``display_memory``.
        """
        if self._locked and not force:
            return
        self.port_7ffd = value
        self.memory.page(0, self.rom_banks[(value >> 4) & 1])
        self.memory.page(3, self.ram_banks[value & 0x07])
        self._locked = bool(value & 0x20)

    def _io_write(self, port: int, value: int) -> None:
        # Decode order matters only for clarity: the masks are mutually exclusive
        # (ULA has A0=0; the AY ports have A15=1; 0x7FFD has A15=0,A1=0).
        if port & 0x01 == 0:                 # 0xFE: ULA border/speaker (base handles + beeper)
            super()._io_write(port, value)
        elif port & 0xC002 == 0xC000:        # 0xFFFD: select AY register
            self.ay.select_register(value)
        elif port & 0xC002 == 0x8000:        # 0xBFFD: write AY register (timestamped)
            self.ay.write_selected(self.frame_t_state, value)
        elif port & 0x8002 == 0:             # 0x7FFD: memory paging
            self.set_paging(value)

    def _io_read(self, port: int) -> int:
        if port & 0xC002 == 0xC000:          # 0xFFFD: read the selected AY register
            return self.ay.read_selected()
        return self.ula.read_port(port)

    def display_memory(self):
        # Shadow-screen (bit 3) shows RAM7 even when it isn't mapped into any slot.
        return self.ram_banks[7 if self.port_7ffd & 0x08 else 5].data

    def paging_state(self) -> Paging128:
        rom_index = (self.port_7ffd >> 4) & 1
        ram_bank = self.port_7ffd & 0x07
        screen_bank = 7 if self.port_7ffd & 0x08 else 5
        labels = (f"ROM{rom_index}", "RAM5", "RAM2", f"RAM{ram_bank}")
        return Paging128(self.port_7ffd, rom_index, ram_bank, screen_bank, self._locked, labels)
