from zxemu_core.cpu.z80 import Z80
from zxemu_core.memory import Bank, Memory


def make_z80() -> Z80:
    memory = Memory([Bank(), Bank(), Bank(), Bank()])
    return Z80(memory)


def test_reset_sets_known_initial_state():
    cpu = make_z80()
    cpu.regs.pc = 0x1234
    cpu.t_states = 999
    cpu.halted = True
    cpu.reset()
    assert cpu.regs.pc == 0x0000
    assert cpu.regs.sp == 0xFFFF
    assert cpu.t_states == 0
    assert cpu.halted is False


def test_read_opcode_advances_pc_and_consumes_4_t_states():
    cpu = make_z80()
    cpu.memory.write_byte(0x0000, 0xAB)
    value = cpu.read_opcode()
    assert value == 0xAB
    assert cpu.regs.pc == 0x0001
    assert cpu.t_states == 4


def test_read_opcode_increments_r_low_7_bits():
    cpu = make_z80()
    cpu.regs.r = 0x00
    cpu.read_opcode()
    assert cpu.regs.r == 0x01


def test_read_opcode_r_wraps_at_7_bits_preserving_bit_7():
    cpu = make_z80()
    cpu.regs.r = 0xFF  # bit 7 set, low 7 bits at max
    cpu.read_opcode()
    assert cpu.regs.r == 0x80  # low 7 bits wrap to 0, bit 7 preserved


def test_fetch_byte_advances_pc_and_consumes_3_t_states_without_touching_r():
    cpu = make_z80()
    cpu.memory.write_byte(0x0000, 0x42)
    cpu.regs.r = 0x10
    value = cpu.fetch_byte()
    assert value == 0x42
    assert cpu.regs.pc == 0x0001
    assert cpu.t_states == 3
    assert cpu.regs.r == 0x10


def test_fetch_word_reads_little_endian_and_advances_pc_by_2():
    cpu = make_z80()
    cpu.memory.write_byte(0x0000, 0xCD)
    cpu.memory.write_byte(0x0001, 0xAB)
    value = cpu.fetch_word()
    assert value == 0xABCD
    assert cpu.regs.pc == 0x0002
    assert cpu.t_states == 6


def test_push_pop_word_round_trips_and_updates_sp():
    cpu = make_z80()
    cpu.regs.sp = 0xFFF0
    cpu.push_word(0x1234)
    assert cpu.regs.sp == 0xFFEE
    value = cpu.pop_word()
    assert value == 0x1234
    assert cpu.regs.sp == 0xFFF0


def test_step_dispatches_a_plain_opcode():
    cpu = make_z80()
    cpu.memory.write_byte(0x0000, 0x00)  # NOP
    t = cpu.step()
    assert cpu.regs.pc == 0x0001
    assert t == 4
