"""Play an :class:`~zxemu_core.sound.ay_program.AyProgram` by running it on a real Z80.

The music in a compiled module or an .ay file *is* a program (see ``ay_program.py``), so
the only faithful way to hear it is to run it -- and this project already has the machine
to run it on. This is the whole player: a 128K, the blob loaded where it belongs, its
initialise routine called once, and its play routine called once per frame while the AY's
output is collected.

**It is not the emulator on screen.** A private machine is built here and thrown away
afterwards, because auditioning a tune must never cost the user the state they were
debugging -- the same reasoning that gave ``beeper_preview.py`` its own standalone Beeper.
Nothing is drawn, no keyboard is attached, and the ROM is blank: no ROM routine is ever
executed, since the blob is self-contained by construction.

**Calling a routine on an emulated CPU** takes one trick worth naming. There is no "call
and return" primitive -- only a CPU that steps. So a *sentinel* return address is pushed
onto the stack, one no music player would ever jump to, and the CPU is stepped until the
program counter arrives there. That is exactly what a ``RET`` will do when the routine
finishes, so the sentinel appearing means the routine returned, and nothing else does.
"""

from __future__ import annotations

from zxemu_core.machine import Machine128
from zxemu_core.sound.ay_program import AyProgram

#: Where a called routine "returns to". Chosen inside the blank ROM, which the music never
#: touches, so seeing the PC here cannot be confused with the program running normally.
_RETURN_SENTINEL = 0x0038

#: How long a single init or play call is allowed to run before it is abandoned, in
#: instructions. A play routine is a few thousand T-states; a runaway one means the file
#: was not what it claimed and the emulated CPU is executing rubbish. That has to be
#: survivable -- the IDE stays responsive and the user gets told -- rather than a hang.
_STEP_LIMIT = 400_000


class RoutineDidNotReturn(RuntimeError):
    """A called routine ran past ``_STEP_LIMIT`` without returning.

    Nearly always means the load address was wrong, so the "player" is really whatever
    those bytes decode to. Distinct from a parse failure because it is discovered by
    *running*, and it is the last line of defence for a headerless format.
    """


class AyModulePlayer:
    """Runs one AY program, one frame at a time, handing back PCM.

    Deliberately shaped like the rest of this package's sound sources: build it, call
    ``render_frame()`` repeatedly, take the samples. Nothing here knows about Qt, audio
    devices or timers, so a test can render a hundred frames as fast as the CPU allows and
    assert on the result.
    """

    def __init__(self, program: AyProgram, sample_rate: int = 44100):
        self.program = program
        # Blank ROMs: 16K of zeros is 16K of NOPs, which is fine because nothing executes
        # there. The sentinel lives in that dead space precisely so an accidental fall-off
        # cannot be mistaken for a normal return.
        self.machine = Machine128(bytes(0x4000), bytes(0x4000))
        self.machine.ay.enabled = True
        self.machine.audio.enabled = True
        self.frames_played = 0
        self._load()
        self._preload_registers()
        self._call(program.init)

    def render_frame(self) -> list[float]:
        """Advance the music by one frame and return that frame's PCM."""
        self._call(self.program.play)
        # The play routine has written its AY registers, each stamped with the T-state it
        # happened at, and the rest of the frame is silence-as-far-as-the-CPU-goes. Jumping
        # the clock to the frame boundary is what a real machine reaching its interrupt
        # would do, and it keeps the chip's timeline honest without emulating idle cycles
        # nobody can hear.
        self.machine.frame_t_state = self.machine.frame_tstates
        self.machine.end_frame()
        self.frames_played += 1
        return self.machine.audio.take_samples()

    def mute(self) -> None:
        """Silence the chip through the program's own mute routine, where it has one.

        Its own, rather than zeroing the registers here: a player may keep state that a
        blunt "all volumes to zero" would leave inconsistent, and it knows how to stop.
        """
        if self.program.mute is not None:
            self._call(self.program.mute)

    def _load(self) -> None:
        for address, data in self.program.blocks:
            for offset, byte in enumerate(data):
                self.machine.memory.write_byte((address + offset) & 0xFFFF, byte)

    def _preload_registers(self) -> None:
        """Fill every common register pair with the program's preload value, if it has one.

        Blanket, deliberately: the format says "the common registers", not "this one", and
        which register a given player actually reads is its own business. An .ay file with
        several tunes usually ships one block of code and picks the tune by this value
        alone, so a player that guessed at, say, HL would play the right song for some
        files and the wrong one for others -- the worst possible failure, being inaudible.
        """
        value = self.program.register_preload
        if value is None:
            return
        regs = self.machine.cpu.regs
        high, low = (value >> 8) & 0xFF, value & 0xFF
        regs.a, regs.f = high, low
        regs.a2, regs.f2 = high, low
        regs.b, regs.c = high, low
        regs.b2, regs.c2 = high, low
        regs.d, regs.e = high, low
        regs.d2, regs.e2 = high, low
        regs.h, regs.l = high, low
        regs.h2, regs.l2 = high, low
        regs.ixh, regs.ixl = high, low
        regs.iyh, regs.iyl = high, low

    def _call(self, address: int) -> None:
        """Call one routine and run until it returns (see the module docstring)."""
        regs = self.machine.cpu.regs
        regs.sp = self.program.stack
        self._push(_RETURN_SENTINEL)
        regs.pc = address
        for _ in range(_STEP_LIMIT):
            if regs.pc == _RETURN_SENTINEL:
                return
            self.machine.frame_t_state += self.machine.cpu.step()
        raise RoutineDidNotReturn(
            "routine at 0x{:04X} ran {} instructions without returning".format(address, _STEP_LIMIT)
        )

    def _push(self, value: int) -> None:
        regs = self.machine.cpu.regs
        regs.sp = (regs.sp - 2) & 0xFFFF
        self.machine.memory.write_byte(regs.sp, value & 0xFF)
        self.machine.memory.write_byte((regs.sp + 1) & 0xFFFF, value >> 8)


def render(program: AyProgram, frames: int, sample_rate: int = 44100) -> list[float]:
    """Render ``frames`` frames of a program in one go -- the headless path, for tests."""
    player = AyModulePlayer(program, sample_rate=sample_rate)
    samples: list[float] = []
    for _ in range(frames):
        samples.extend(player.render_frame())
    return samples
