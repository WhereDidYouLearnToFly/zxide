from zxemu_core.machine import Machine
from zxemu_core.ula import FRAME_TSTATES


def make_machine() -> Machine:
    rom = bytearray(0x4000)
    rom[0] = 0x00  # NOP at reset vector; rest is zero (also NOP), keeps the CPU busy-looping harmlessly
    return Machine(bytes(rom))


def test_reset_sets_pc_to_zero_and_im1():
    m = make_machine()
    assert m.cpu.regs.pc == 0x0000
    assert m.cpu.regs.im == 1
    assert m.frame_t_state == 0


def test_out_to_port_fe_sets_ula_border_color():
    m = make_machine()
    m.cpu.io_write(0xFE, 0x03)
    assert m.ula.border_color == 0x03


def test_in_from_port_fe_reads_ula():
    m = make_machine()
    assert m.cpu.io_read(0xFE) == m.ula.read_port(0xFE)


def test_run_frame_advances_t_states_by_frame_budget():
    m = make_machine()
    m.run_frame()
    # NOP-only ROM: frame_t_state should have wrapped back into [0, small) after
    # exactly filling one frame budget (each NOP = 4 T-states, divides evenly).
    assert m.frame_t_state == 0
    assert m.cpu.t_states >= FRAME_TSTATES


def test_run_frame_fires_interrupt_that_can_wake_halt():
    rom = bytearray(0x4000)
    rom[0] = 0x76  # HALT at the reset vector
    m = Machine(bytes(rom))
    m.cpu.regs.im = 1
    # iff1 is False post-reset (DI state), so this first frame's interrupt is masked
    # and HALT actually executes and holds for the rest of the frame.
    m.run_frame()
    assert m.cpu.halted is True
    assert m.cpu.regs.pc == 0x0001  # parked just past the HALT while it holds

    m.cpu.regs.iff1 = True  # simulate an EI having happened
    initial_sp = m.cpu.regs.sp
    m.run_frame()  # this frame's leading interrupt should wake the halt
    assert m.cpu.halted is False
    assert m.cpu.regs.sp == (initial_sp - 2) & 0xFFFF  # the interrupt pushed a return address


def test_multiple_frames_accumulate_t_states():
    m = make_machine()
    m.run_frame()
    first = m.cpu.t_states
    m.run_frame()
    assert m.cpu.t_states > first


def test_keyboard_press_is_visible_to_cpu_in_instruction():
    m = make_machine()
    m.keyboard.press("Z")  # row 0 (0xFEFE), bit 1
    value = m.cpu.io_read(0xFEFE)
    assert value & 0b00010 == 0  # bit 1 low: Z held
    assert value & 0b00001 != 0  # bit 0 high: CAPS SHIFT not held


def test_out_to_port_fe_sets_ula_speaker_bit():
    m = make_machine()
    m.cpu.io_write(0xFE, 0x10)  # bit 4 high
    assert m.ula.speaker == 1
    m.cpu.io_write(0xFE, 0x00)  # bit 4 low
    assert m.ula.speaker == 0


def test_beeper_is_disabled_by_default_so_audio_is_free():
    """With audio off (the default), speaker flips record nothing."""
    m = make_machine()
    m.cpu.io_write(0xFE, 0x10)
    m.cpu.io_write(0xFE, 0x00)
    m.beeper.end_frame(FRAME_TSTATES)
    assert m.beeper.take_samples() == []


def test_machine_timestamps_speaker_flips_at_the_frame_clock():
    """An enabled beeper records each *change* to the speaker bit, at frame_t_state."""
    m = make_machine()
    m.beeper.enabled = True

    m.frame_t_state = 1000
    m.cpu.io_write(0xFE, 0x10)  # -> high at t=1000
    m.frame_t_state = 1000  # unchanged bit: a border-only write must not record an edge
    m.cpu.io_write(0xFE, 0x13)  # still bit4 high, just border bits -> no new edge
    m.frame_t_state = 5000
    m.cpu.io_write(0xFE, 0x00)  # -> low at t=5000

    assert m.beeper._edges == [(1000, 1), (5000, 0)]
