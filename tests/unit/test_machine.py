from zxemu_core.machine import Machine, Machine128
from zxemu_core.ula import FRAME_TSTATES, FRAME_TSTATES_128K


def make_machine() -> Machine:
    rom = bytearray(0x4000)
    rom[0] = 0x00  # NOP at reset vector; rest is zero (also NOP), keeps the CPU busy-looping harmlessly
    return Machine(bytes(rom))


def make_machine128() -> Machine128:
    return Machine128(bytes(0x4000), bytes(0x4000))


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


# --- 128K machine --------------------------------------------------------------


def test_machine128_uses_the_longer_128k_frame():
    assert make_machine128().frame_tstates == FRAME_TSTATES_128K == 70908


def test_base_machine_has_no_paging_and_shows_slot1():
    m = make_machine()
    assert m.paging_state() is None
    assert m.display_memory() is m.memory.slots[1].data


def test_machine128_powers_on_with_standard_paging():
    m = make_machine128()
    ps = m.paging_state()
    assert (ps.port_7ffd, ps.rom_index, ps.ram_bank, ps.screen_bank, ps.locked) == (0, 0, 0, 5, False)
    assert ps.slot_labels == ("ROM0", "RAM5", "RAM2", "RAM0")
    assert m.display_memory() is m.ram_banks[5].data


def test_machine128_pages_ram_and_rom_via_7ffd():
    m = make_machine128()
    m._io_write(0x7FFD, 0x13)  # RAM3 (bits 0-2) + ROM1 (bit 4)
    assert m.memory.slots[3] is m.ram_banks[3]
    assert m.memory.slots[0] is m.rom_banks[1]
    assert m.paging_state().slot_labels == ("ROM1", "RAM5", "RAM2", "RAM3")


def test_machine128_shadow_screen_select():
    m = make_machine128()
    assert m.display_memory() is m.ram_banks[5].data
    m._io_write(0x7FFD, 0x08)  # bit 3 -> shadow screen (RAM7)
    assert m.display_memory() is m.ram_banks[7].data
    assert m.paging_state().screen_bank == 7


def test_machine128_paging_lock_blocks_further_writes_until_reset():
    m = make_machine128()
    m._io_write(0x7FFD, 0x23)  # RAM3 + lock (bit 5): the locking write still applies
    assert m.memory.slots[3] is m.ram_banks[3]
    assert m.paging_state().locked is True
    m._io_write(0x7FFD, 0x01)  # ignored while locked
    assert m.memory.slots[3] is m.ram_banks[3]
    m.set_paging(0x01, force=True)  # snapshot restore bypasses the lock
    assert m.memory.slots[3] is m.ram_banks[1]


def test_machine128_reset_clears_lock_and_restores_map():
    m = make_machine128()
    m._io_write(0x7FFD, 0x27)  # page + lock
    m.reset()
    ps = m.paging_state()
    assert ps.locked is False
    assert ps.port_7ffd == 0
    assert m.memory.slots[3] is m.ram_banks[0]


def test_machine128_ignores_ports_that_are_not_7ffd():
    m = make_machine128()
    m._io_write(0x7FFD, 0x03)          # RAM3 in slot 3
    m._io_write(0x7FFF, 0x05)          # A1 set -> not the paging port, must be ignored
    assert m.paging_state().ram_bank == 3


def test_machine128_ay_register_read_write_through_ports():
    m = make_machine128()
    m._io_write(0xFFFD, 0x08)          # select AY register 8
    m._io_write(0xBFFD, 0xFF)          # write it (5-bit register)
    assert m._io_read(0xFFFD) == 0x1F


def test_block_instruction_stays_within_the_frame_loop():
    """A large repeated block op (LDIR clearing a big buffer) must run one iteration
    per step() so the frame loop reclaims control -- it must NOT swallow the whole
    move in a single step and overshoot the frame by many frames' worth of T-states
    (which desynced beeper/AY timestamps and silenced 128K sound at boot).
    """
    rom = bytearray(0x4000)
    rom[0x00] = 0x01              # LD BC,0x4000  (clear a 16K block)
    rom[0x01] = 0x00
    rom[0x02] = 0x40
    rom[0x03] = 0x21              # LD HL,0x8000
    rom[0x04] = 0x00
    rom[0x05] = 0x80
    rom[0x06] = 0x11              # LD DE,0x8001
    rom[0x07] = 0x01
    rom[0x08] = 0x80
    rom[0x09] = 0xED              # LDIR
    rom[0x0A] = 0xB0
    m = Machine(bytes(rom))
    m.run_frame()
    # One 70k-T frame can't finish a 16K LDIR (~344k T), so the CPU is still on the
    # LDIR with PC rewound to it -- the block did NOT run atomically past the frame.
    assert m.frame_t_state < FRAME_TSTATES  # no giant overshoot
    assert m.cpu.regs.pc == 0x0009          # still parked on the (repeating) LDIR
    assert m.cpu.regs.bc != 0               # not yet finished
