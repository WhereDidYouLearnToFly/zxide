"""Spectrum machines: wire CPU + paged memory + ULA + sound together and run frames.

``Machine`` is the 48K; ``Machine128`` extends it with the 128K's bank paging (port
0x7FFD) and AY sound chip; ``MachinePentagon`` extends *that* into the Soviet clone.
The 48K wiring is factored into ``_wire()`` so each subclass can build a different
memory map first and then reuse the exact same CPU/ULA/sound plumbing.

The machine is also where the pieces that need a *whole* Spectrum live, because no
single chip owns them:

  * **audio timestamps** -- the ULA records the speaker bit, but only the machine
    knows the frame clock, so it is the machine that timestamps each flip,
  * **the tape**, in both of its forms -- fast loading means intercepting the ROM at a
    specific address, which needs the CPU and the memory map together
    (``_tape_trap``); edge replay means answering "what is on the wire *now*", which
    needs a clock that doesn't restart every frame (``tape_tstate``).
"""

from __future__ import annotations

from typing import NamedTuple

from .cpu.z80 import Z80
from .keyboard import Keyboard
from .memory import Bank, Memory, create_48k_memory, create_128k_memory
from .mouse import KempstonMouse
from .sound.ay import AY8912
from .sound.beeper import Beeper
from .sound.mixer import SoundMixer
from .storage import pulse, tape
from .storage.disk.beta import DRIVE_COUNT, Beta128
from .storage.disk.wd1793 import WD1793
from .ula import FRAME_TSTATES, FRAME_TSTATES_128K, FRAME_TSTATES_PENTAGON, LINE_TSTATES, SCREEN_START_TSTATE, Ula

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
        self.mouse = KempstonMouse()
        self.ula = Ula(keyboard=self.keyboard)
        # Audio pipeline: a mixer fed by one or more sound sources. The 48K has just
        # the beeper; Machine128 adds the AY. It stays dormant (no samples, no cost)
        # until a UI layer switches ``audio.enabled`` on.
        self.beeper = Beeper()
        self.audio = SoundMixer(sample_rate=self.beeper.sample_rate)
        self.audio.add_source(self.beeper)
        self._speaker_level = 0  # last speaker bit we handed to the beeper
        self.frame_tstates = FRAME_TSTATES  # per-model frame length (128K overrides)
        # Where a frame T-state falls on the screen, for drawing mid-frame border
        # changes. One line's worth of T-states, and the T-state the first pixel row
        # begins at -- everything before that is top border, everything after the last
        # pixel row is bottom border. 128K restates both; see LINE_TSTATES there.
        self.line_tstates = LINE_TSTATES
        self.screen_start_tstate = SCREEN_START_TSTATE
        self.frame_t_state = 0
        # T-states elapsed in whole frames so far. frame_t_state restarts every frame,
        # but a tape doesn't: a pulse can straddle a frame boundary, and a pause runs
        # for a whole second. Adding the two gives a clock that only ever goes up.
        self._frame_base = 0
        # Tape: a TapeDeck when a tape is inserted, else None, plus the edge player that
        # plays it as real pulses. The two loaders are independent -- fast loading serves
        # anything that calls the ROM, the player serves everything else, including the
        # turbo loaders that no trap can reach -- and they share the deck's play head.
        # Both models get this identically (the 48K and 128K share LD-BYTES).
        self.tape: tape.TapeDeck | None = None
        self.tape_player: pulse.TapePlayer | None = None
        self.fast_load_enabled = True
        self.tape_audible = True  # let the tape signal reach the speaker, as it does in hardware
        self.cpu.set_trap(tape.LD_BYTES_TRAP, self._tape_trap)
        self.set_port_watchpoints()  # none: installs the plain, uninstrumented io hooks
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

    def rom_symbols_valid(self) -> bool:
        """Whether the 48K ROM routine names describe the ROM currently paged in.

        Always true on a 48K -- there is only one ROM. Machine128 overrides this,
        because with the 128 editor ROM paged those addresses hold different code and
        labelling them would actively mislead (see zxemu_core.debug.rom_symbols).
        """
        return True

    # --- tape -----------------------------------------------------------------

    @property
    def tape_tstate(self) -> int:
        """A T-state clock that never restarts -- what the edge player measures against.

        Everything else here works in frame-relative time because everything else is
        finished inside a frame. A tape is the exception: it is a continuous signal
        that knows nothing about the 50Hz interrupt it happens to be playing under.
        """
        return self._frame_base + self.frame_t_state

    def insert_tape(self, deck: tape.TapeDeck | None) -> None:
        """Put a tape in the deck (or None to eject); rewound to its first block."""
        self.tape = deck
        if deck is None:
            self.tape_player = None
        else:
            deck.rewind()
            self.tape_player = pulse.TapePlayer(deck, start_clock=self.tape_tstate)

    def eject_tape(self) -> None:
        self.tape = None
        self.tape_player = None
        self.ula.ear_level = 1  # nothing on the wire: back to the idle read

    def _tape_trap(self):
        """CPU trap inside LD-BYTES: fast-load the next block, or decline (return None).

        Declines -- letting the ROM run the routine for real -- when there's no tape or
        fast loading is off. It also verifies the routine really is LD-BYTES, by its
        preamble (``INC D`` / ``EX AF,AF'`` at 0x0556) *and* the ``IN A,($FE)`` at the
        trap address itself: on the 128K that is only true while the 48-BASIC ROM is
        paged, so the trap never misfires inside the 128 menu ROM, and on the 48K it is a
        cheap sanity guard. Returns the billed T-states when it acts.
        """
        if self.tape is None or not self.fast_load_enabled:
            return None
        if (self.memory.read_byte(0x0556) != 0x14
                or self.memory.read_byte(0x0557) != 0x08
                or self.memory.read_byte(tape.LD_BYTES_TRAP) != 0xDB):
            return None  # not the real LD-BYTES (wrong ROM paged) -- don't intercept
        return TAPE_TRAP_TSTATES if tape.fast_load(self, self.tape) else None

    # --- port watchpoints -----------------------------------------------------

    def set_port_watchpoints(self, reads=(), writes=()) -> None:
        """Watch IN/OUT on these ports, or clear the watch when both are empty.

        Rather than testing "is anything watched?" on every port access, this *swaps
        the CPU's io hooks*: with no watchpoints the CPU calls the plain ``_io_read`` /
        ``_io_write`` and pays literally nothing -- not even a branch. That matters
        more than it looks: a PWM beeper engine can do 80,000 OUTs in a single frame,
        so even an empty-set check on the fast path would cost real milliseconds.

        Port matching follows how the Spectrum actually decodes: a watch value of
        0x00-0xFF matches the *low byte* of the address (so watching 0xFE catches every
        ULA access, whatever the high byte holds), while a 16-bit value must match
        exactly (so 0x7FFD means the paging port and nothing else).
        """
        self.watch_ports_read = set(reads)
        self.watch_ports_write = set(writes)
        self.port_watch_hit: PortWatchHit | None = None
        watching = bool(self.watch_ports_read or self.watch_ports_write)
        self.cpu.io_read = self._io_read_watched if watching else self._io_read
        self.cpu.io_write = self._io_write_watched if watching else self._io_write

    @staticmethod
    def _port_matches(port: int, watched: set) -> bool:
        return port in watched or (port & 0xFF) in watched

    def _io_read_watched(self, port: int) -> int:
        value = self._io_read(port)
        if self._port_matches(port, self.watch_ports_read):
            self.port_watch_hit = PortWatchHit(False, port, value, self.cpu.regs.pc)
        return value

    def _io_write_watched(self, port: int, value: int) -> None:
        self._io_write(port, value)
        if self._port_matches(port, self.watch_ports_write):
            self.port_watch_hit = PortWatchHit(True, port, value, self.cpu.regs.pc)

    # --- IO + frame loop ------------------------------------------------------

    def _io_read(self, port: int) -> int:
        # Kempston Mouse: a handful of exact 16-bit addresses, decoded before anything
        # else so they can never be mistaken for the ULA's partial (low-byte-only)
        # decode of port 0xFE -- their low byte (0xDF) has bit 0 set, so they'd fall
        # through to the ULA/tape path below anyway, but checking first keeps the
        # mouse self-contained and costs one dict-free tuple compare when disabled.
        if self.mouse.enabled and KempstonMouse.handles(port):
            return self.mouse.read_port(port)
        # Tape input. Only the machine knows the continuous clock the player measures
        # against, exactly as it is the machine that timestamps the speaker on the way
        # out. The check costs one attribute compare per IN when no tape is inserted.
        if self.tape_player is not None and port & 0x01 == 0:
            self.ula.ear_level = self.tape_player.ear_level(self.tape_tstate)
            if self.beeper.enabled:
                self._refresh_speaker()
        return self.ula.read_port(port)

    def _io_write(self, port: int, value: int) -> None:
        previous_border = self.ula.border_color
        self.ula.write_port(port, value)
        # Log border changes with the clock, so the renderer can draw the bands a real
        # ULA would paint. Only *changes* are recorded, which keeps this off the hot
        # path that matters: a PWM beeper engine hammering 0xFE writes the same border
        # bits every time and appends nothing, paying one compare per OUT.
        if self.ula.border_color != previous_border:
            self.ula.border_changes.append((self.frame_t_state, self.ula.border_color))
        if self.beeper.enabled:
            self._refresh_speaker()

    def _refresh_speaker(self) -> None:
        """Timestamp a change in what the speaker is doing, from either of its sources.

        Two things drive that one cone. The CPU's ``OUT`` to bit 4 is the obvious one.
        The other is the tape: on real hardware the EAR input is summed into the same
        amplifier, which is *why* you hear a tape screeching while it loads rather than
        loading in silence. Modelling that as an OR of two 1-bit sources is crude next
        to the analogue mix, but it puts the loading sound where it belongs -- and it
        costs nothing, since both are already 1-bit here (see ``sound/beeper.py`` on
        the related two-bit simplification).

        frame_t_state is the clock at the *start* of the current instruction (its
        T-states are added after step() returns), so a flip is placed a few T-states
        early -- inaudible, and it keeps the audio timing entirely inside the Machine.
        """
        level = self.ula.speaker
        if self.tape_audible and self.tape_player is not None and self.tape_player.motor:
            level |= self.ula.ear_level
        if level != self._speaker_level:
            self._speaker_level = level
            self.beeper.set_level(self.frame_t_state, level)

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
        self.end_frame()

    def end_frame(self) -> None:
        """Close out one frame: carry the remainder, run the tape motor, resample sound.

        Separate from :meth:`run_frame` because ``run_frame`` is not the only way to
        execute a frame. A debugger steps instruction by instruction so it can stop
        anywhere, and it must still reach this seam -- otherwise no PCM is ever produced
        and the machine falls silent for as long as you are debugging, which is not what
        "run slowly" should mean.
        """
        # Carry the sub-frame remainder so the average frame length stays exact. Block
        # instructions run one iteration per step() (see blockio.py), so a single step
        # never overshoots by more than a few T-states -- the remainder stays small and
        # audio timestamps stay in-frame.
        self.frame_t_state -= self.frame_tstates
        self._frame_base += self.frame_tstates  # keep tape_tstate continuous across the seam
        self.ula.end_frame()  # hand the finished border log to whoever draws the picture
        if self.tape_player is not None:
            # The player decides once per frame whether the machine is actually
            # listening to the tape, and runs the motor if so -- see pulse.py.
            self.tape_player.end_frame()
        # Close out the frame's audio: resample the sound sources' activity gathered
        # above into PCM the UI can play. A no-op while audio is disabled.
        self.audio.end_frame(self.frame_tstates)


class PortWatchHit(NamedTuple):
    """Records the IN/OUT that tripped a port watchpoint."""

    is_write: bool
    port: int
    value: int
    pc: int  # the instruction that did it (PC is already past it by the time we look)


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

    #: PAL frame length. A class attribute rather than a literal in __init__ so
    #: MachinePentagon can state its own without re-implementing the constructor.
    FRAME_TSTATES = FRAME_TSTATES_128K

    #: The 128K's line is four T-states longer than the 48K's, and its screen therefore
    #: starts a little later -- both matter only for placing mid-frame border changes.
    #: MachinePentagon inherits these: its line length is 224 like the 48K's, but where
    #: its screen begins is not something this codebase has verified, so it is left
    #: stated here rather than guessed at separately.
    LINE_TSTATES = 228
    SCREEN_START_TSTATE = 63 * 228  # 14364

    #: Whether the odd RAM banks share the memory bus with the ULA. True on a Sinclair
    #: 128K; MachinePentagon sets it False, because the clone's ULA contends with nothing.
    contended_ram = True

    def __init__(self, rom0_data: bytes, rom1_data: bytes):
        self.memory, self.rom_banks, self.ram_banks = create_128k_memory(
            rom0_data, rom1_data, contended=self.contended_ram
        )
        self.port_7ffd = 0
        self._locked = False
        #: Called with the new RAM bank number whenever paging changes. Declared before
        #: _wire(), which resets and therefore pages, so the very first mapping is
        #: announced too rather than being missed until the program happens to page.
        self.paging_listener = None
        self._wire()  # cpu/ula/keyboard/beeper/mixer + reset (see base Machine)
        self.frame_tstates = self.FRAME_TSTATES
        self.line_tstates = self.LINE_TSTATES
        self.screen_start_tstate = self.SCREEN_START_TSTATE
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
        self.memory.page(0, self.rom_for_slot0())
        self.memory.page(3, self.ram_banks[value & 0x07])
        self._locked = bool(value & 0x20)
        if self.paging_listener is not None:
            # Announce the change; the machine does not care who is listening. The
            # debugger's coverage map uses it to record *which bank* an address above
            # 0xC000 belonged to -- something no amount of later analysis can recover,
            # and which is free to note here because this is the one place the mapping
            # moves, reached only on a port write.
            self.paging_listener(value & 0x07)

    def rom_for_slot0(self):
        """Which ROM bank belongs at 0x0000 for the current paging latch.

        A seam, not ceremony: on a Pentagon the Beta 128 interface can have substituted
        TR-DOS for the ROM, and a 0x7FFD write must not silently undo that -- a program
        switching RAM banks mid-load would otherwise pull TR-DOS out from under itself.
        """
        return self.rom_banks[(self.port_7ffd >> 4) & 1]

    def restore_rom_slot(self) -> None:
        """Put the paging latch's ROM back in slot 0 (used when TR-DOS pages out)."""
        self.memory.page(0, self.rom_banks[(self.port_7ffd >> 4) & 1])

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
        # Everything else is the base machine's read, *including* its tape handling --
        # a 128K loads tapes exactly as a 48K does, so answering the ULA directly here
        # would quietly leave the 128 with no tape input at all.
        return super()._io_read(port)

    def display_memory(self):
        # Shadow-screen (bit 3) shows RAM7 even when it isn't mapped into any slot.
        return self.ram_banks[7 if self.port_7ffd & 0x08 else 5].data

    def rom_symbols_valid(self) -> bool:
        # ROM 1 is 48 BASIC -- the ROM the traditional routine names describe.
        return ((self.port_7ffd >> 4) & 1) == 1

    def paging_state(self) -> Paging128:
        rom_index = (self.port_7ffd >> 4) & 1
        ram_bank = self.port_7ffd & 0x07
        screen_bank = 7 if self.port_7ffd & 0x08 else 5
        labels = ("ROM{}".format(rom_index), "RAM5", "RAM2", "RAM{}".format(ram_bank))
        return Paging128(self.port_7ffd, rom_index, ram_bank, screen_bank, self._locked, labels)


class MachinePentagon(Machine128):
    """A Pentagon 128: the Soviet-bloc clone that most of the demoscene was written on.

    Electrically it is a 128K rebuilt in discrete logic rather than a Ferranti ULA, and
    for emulation purposes that reduces to exactly three differences:

      * **A 71680 T-state frame** (224 lines of 320 T) instead of the Sinclair's 70908.
        A 50Hz interrupt therefore lands on a different cadence, and code timed against
        one model runs visibly wrong on the other -- which is the whole reason this is a
        separate machine and not "a 128K with a disk drive".
      * **No memory contention at all.** The clone's designers did not reproduce the
        ULA's habit of stalling the CPU when it wants the same bank. Note that this makes
        us *more* faithful here than on the Sinclair models, not less: there is nothing
        to approximate.
      * **A Beta 128 disk interface, built in and live from reset**, with TR-DOS in a
        third ROM (see ``zxemu_core/storage/disk/beta.py``). That is what the machine is
        actually for; tape was already a legacy format by the time it shipped.

    Paging, the AY, the bank pool and the screen are pure 128K, which is why this class
    is as short as it is -- ``Machine128`` already does all of that.
    """

    FRAME_TSTATES = FRAME_TSTATES_PENTAGON
    contended_ram = False

    def reset(self) -> None:
        """Power-cycle, which on this machine has to take the disk interface with it.

        The reset line reaches the Beta 128 too: its ROM drops out of the map and the
        controller aborts whatever it was doing. Skipping that is not a cosmetic
        omission -- ``Machine128.reset`` re-pages slot 0 through ``rom_for_slot0()``,
        which answers "TR-DOS" while the interface is paged in, so a reset performed
        from inside TR-DOS would leave TR-DOS sitting at 0x0000 and start executing it
        from address 0. The machine comes up as garbage and the Reset button looks
        broken, which is exactly how this was found.
        """
        if getattr(self, "beta", None) is not None:
            self.beta.paged = False
            if self.beta.controller is not None:
                self.beta.controller.master_reset()
        super().reset()

    def __init__(self, rom0_data: bytes, rom1_data: bytes, trdos_rom_data: bytes | None = None):
        # Declared *before* the base constructor, not after: it runs reset() -> set_paging()
        # -> rom_for_slot0(), which asks whether the Beta has taken over slot 0. Assigning
        # afterwards leaves that first call reading an attribute that does not exist yet.
        self.beta = None
        # Four drive slots, as the interface's connector has. Each holds a mounted image
        # or None; the UI mounts into them and the controller reads through them.
        self.beta_drives: list = [None] * DRIVE_COUNT
        super().__init__(rom0_data, rom1_data)
        # TR-DOS lives in a *third* ROM that isn't part of the 0x7FFD pool -- the Beta
        # interface substitutes it for whatever slot 0 holds, rather than being selected
        # by the paging latch. Optional so a Pentagon can still be constructed in tests
        # (and by anyone who deleted the ROM over its licensing) without a disk system.
        if trdos_rom_data is not None:
            self.trdos_rom = Bank.from_bytes(trdos_rom_data, readonly=True)
            # The controller's only use for a clock is the index pulse, and tape_tstate is
            # already exactly what it needs: a count that never restarts.
            controller = WD1793(self.beta_drives, clock=lambda: self.tape_tstate)
            self.beta = Beta128(self, self.trdos_rom, controller)
            # The interface watches the address bus, so it needs to see every fetch.
            self.cpu.m1_hook = self.beta.m1

    def rom_for_slot0(self):
        # While TR-DOS is paged, a 0x7FFD write changes which ROM *would* be visible
        # without disturbing what actually is -- see Machine128.rom_for_slot0.
        if self.beta is not None and self.beta.paged:
            return self.trdos_rom
        return super().rom_for_slot0()

    def _io_read(self, port: int) -> int:
        if self.beta is not None and self.beta.handles(port):
            return self.beta.read_port(port)
        return super()._io_read(port)

    def _io_write(self, port: int, value: int) -> None:
        if self.beta is not None and self.beta.handles(port):
            self.beta.write_port(port, value)
            return
        super()._io_write(port, value)

    def rom_symbols_valid(self) -> bool:
        # With TR-DOS paged, 0x0000-0x3FFF is the disk operating system, so the 48K ROM's
        # routine names would label the wrong code entirely.
        if self.beta is not None and self.beta.paged:
            return False
        return super().rom_symbols_valid()

    def paging_state(self) -> Paging128:
        state = super().paging_state()
        if self.beta is None or not self.beta.paged:
            return state
        # Say what is actually at 0x0000. The memory map showing "ROM1" while TR-DOS is
        # running is the kind of quiet lie that costs an hour in the debugger.
        return state._replace(slot_labels=("TR-DOS",) + state.slot_labels[1:])
