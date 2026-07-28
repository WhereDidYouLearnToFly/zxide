"""Running an AY program on a private emulated machine.

The fixture here is a hand-written Z80 "music player" of a few bytes -- it sets one AY tone
period and volume and returns -- because the point under test is the *harness*, not anyone's
music: does the blob get loaded, does init run, does play run once per frame, does the chip
produce sound, and does a routine that never returns get abandoned rather than hanging the
IDE. Real modules are exercised by hand; a copyrighted tune is not a unit-test fixture.
"""

import pytest

from zxemu_core.sound.ay_module_player import AyModulePlayer, RoutineDidNotReturn, render
from zxemu_core.sound.ay_program import AyProgram

ORG = 0xC000


def _ay_write(register: int, value: int) -> bytes:
    """Z80 for "select an AY register and write it": OUT (0xFFFD),reg / OUT (0xBFFD),value."""
    return bytes([
        0x01, 0xFD, 0xFF,        # LD BC,0xFFFD
        0x3E, register,          # LD A,register
        0xED, 0x79,              # OUT (C),A
        0x01, 0xFD, 0xBF,        # LD BC,0xBFFD
        0x3E, value,             # LD A,value
        0xED, 0x79,              # OUT (C),A
    ])


def _program(init: bytes = b"\xC9", play: bytes = b"\xC9") -> AyProgram:
    """A blob with init at ORG+0 and play at ORG+0x40, mirroring a real module's layout."""
    blob = bytearray(0x100)
    blob[0x00:0x00 + len(init)] = init
    blob[0x40:0x40 + len(play)] = play
    return AyProgram(blocks=[(ORG, bytes(blob))], init=ORG, play=ORG + 0x40, mute=None)


def test_the_blob_is_loaded_where_it_belongs():
    player = AyModulePlayer(_program())
    assert player.machine.memory.read_byte(ORG) == 0xC9


def test_init_runs_once_at_construction():
    """A player that never called init would still make noise on some modules -- from
    whatever the registers happened to hold -- so this is worth pinning."""
    init = _ay_write(8, 15) + b"\xC9"   # channel A volume = 15
    player = AyModulePlayer(_program(init=init))
    assert player.machine.ay._reg[8] == 15


def test_play_runs_once_per_frame():
    """Counted by having the routine write an incrementing value nowhere near the AY: the
    frame count is the contract, and a player called twice per frame plays at double speed
    while sounding entirely plausible."""
    play = bytes([0x3A, 0x00, 0xD0, 0x3C, 0x32, 0x00, 0xD0, 0xC9])  # LD A,(0xD000): INC A: LD (0xD000),A: RET
    player = AyModulePlayer(_program(play=play))
    for _ in range(7):
        player.render_frame()
    assert player.machine.memory.read_byte(0xD000) == 7
    assert player.frames_played == 7


def test_a_frame_of_pcm_comes_back():
    play = _ay_write(0, 0x80) + _ay_write(7, 0x3E) + _ay_write(8, 15) + b"\xC9"
    samples = AyModulePlayer(_program(play=play)).render_frame()
    assert len(samples) == 44100 // 50
    assert any(abs(s) > 0.0 for s in samples)


def test_a_program_that_touches_nothing_settles_to_silence():
    """The chip is only as loud as the program makes it -- no hum, no idle tone.

    Not bit-exact zero, and the reason is worth knowing: an untouched AY starts at a DC
    offset which its DC blocker removes over the first frame (a step of -0.25 decaying to
    about -0.003 by the frame's end). That is the chip's own behaviour, present with no CPU
    running at all, so what this asserts is that the *player* adds nothing on top of it.
    """
    samples = render(_program(), frames=5)
    settled = samples[len(samples) // 5:]  # everything after the first frame
    assert samples
    assert max(abs(s) for s in settled) < 0.01


def test_a_routine_that_never_returns_is_abandoned_not_waited_for():
    """The last line of defence for a headerless format: if the load address was wrong, the
    "player" is whatever those bytes decode to. That has to surface as an error the IDE can
    report, never as a frozen window."""
    forever = bytes([0x18, 0xFE])  # JR -2
    with pytest.raises(RoutineDidNotReturn):
        AyModulePlayer(_program(init=forever))


def test_the_preview_machine_is_private_to_the_player():
    """Two players must not share state, and neither may touch the emulator on screen --
    auditioning a tune cannot cost somebody the session they were debugging."""
    one = AyModulePlayer(_program(init=_ay_write(8, 15) + b"\xC9"))
    two = AyModulePlayer(_program())
    assert one.machine is not two.machine
    assert one.machine.ay._reg[8] == 15
    assert two.machine.ay._reg[8] == 0


def test_mute_is_optional():
    """Not every format defines one; asking for it must not be an error."""
    AyModulePlayer(_program()).mute()  # must not raise
