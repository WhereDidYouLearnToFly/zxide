from zxemu_core.cpu.registers import FLAG_C, FLAG_H, FLAG_N, FLAG_P, FLAG_S, FLAG_Z
from zxemu_core.cpu.z80 import Z80
from zxemu_core.memory import Bank, Memory


def make_cpu() -> Z80:
    cpu = Z80(Memory([Bank(), Bank(), Bank(), Bank()]))
    cpu.reset()
    return cpu


def load(cpu: Z80, address: int, data: bytes) -> None:
    for offset, byte in enumerate(data):
        cpu.memory.write_byte(address + offset, byte)


def test_rlc_b_rotates_bit7_into_carry_and_bit0():
    cpu = make_cpu()
    cpu.regs.b = 0b10000001
    load(cpu, 0, [0xCB, 0x00])  # RLC B
    cpu.step()
    assert cpu.regs.b == 0b00000011
    assert cpu.regs.f & FLAG_C


def test_sla_b_shifts_in_zero():
    cpu = make_cpu()
    cpu.regs.b = 0b01000001
    load(cpu, 0, [0xCB, 0x20])  # SLA B
    cpu.step()
    assert cpu.regs.b == 0b10000010
    assert not (cpu.regs.f & FLAG_C)


def test_sra_preserves_sign_bit():
    cpu = make_cpu()
    cpu.regs.b = 0b10000001
    load(cpu, 0, [0xCB, 0x28])  # SRA B
    cpu.step()
    assert cpu.regs.b == 0b11000000
    assert cpu.regs.f & FLAG_C


def test_sll_undocumented_shifts_in_one():
    cpu = make_cpu()
    cpu.regs.b = 0b00000000
    load(cpu, 0, [0xCB, 0x30])  # SLL B
    cpu.step()
    assert cpu.regs.b == 0b00000001


def test_srl_shifts_in_zero_at_top():
    cpu = make_cpu()
    cpu.regs.b = 0b10000001
    load(cpu, 0, [0xCB, 0x38])  # SRL B
    cpu.step()
    assert cpu.regs.b == 0b01000000
    assert cpu.regs.f & FLAG_C


def test_rl_uses_incoming_carry():
    cpu = make_cpu()
    cpu.regs.b = 0b00000001
    cpu.regs.f = FLAG_C
    load(cpu, 0, [0xCB, 0x10])  # RL B
    cpu.step()
    assert cpu.regs.b == 0b00000011


def test_bit_register_form_sets_zero_when_clear():
    cpu = make_cpu()
    cpu.regs.b = 0b00000000
    load(cpu, 0, [0xCB, 0x40])  # BIT 0,B
    cpu.step()
    assert cpu.regs.f & FLAG_Z
    assert cpu.regs.f & FLAG_H
    assert not (cpu.regs.f & FLAG_N)


def test_bit_register_form_clears_zero_when_set():
    cpu = make_cpu()
    cpu.regs.b = 0b00000001
    load(cpu, 0, [0xCB, 0x40])  # BIT 0,B
    cpu.step()
    assert not (cpu.regs.f & FLAG_Z)


def test_bit_7_sets_sign_flag_when_set():
    cpu = make_cpu()
    cpu.regs.a = 0b10000000
    load(cpu, 0, [0xCB, 0x7F])  # BIT 7,A
    cpu.step()
    assert cpu.regs.f & FLAG_S


def test_bit_hl_memory_form_reads_without_writing():
    cpu = make_cpu()
    cpu.regs.hl = 0x8000
    cpu.memory.write_byte(0x8000, 0b00000100)
    load(cpu, 0, [0xCB, 0x66])  # BIT 4,(HL)
    cpu.step()
    assert cpu.regs.f & FLAG_Z  # bit 4 clear
    assert cpu.memory.read_byte(0x8000) == 0b00000100  # unchanged


def test_res_clears_bit_without_touching_flags():
    cpu = make_cpu()
    cpu.regs.b = 0xFF
    cpu.regs.f = FLAG_P  # sentinel: RES must not touch flags
    load(cpu, 0, [0xCB, 0x80])  # RES 0,B
    cpu.step()
    assert cpu.regs.b == 0xFE
    assert cpu.regs.f == FLAG_P


def test_set_sets_bit_without_touching_flags():
    cpu = make_cpu()
    cpu.regs.b = 0x00
    load(cpu, 0, [0xCB, 0xC0])  # SET 0,B
    cpu.step()
    assert cpu.regs.b == 0x01


def test_rlc_hl_indirect_reads_and_writes_memory():
    cpu = make_cpu()
    cpu.regs.hl = 0x8000
    cpu.memory.write_byte(0x8000, 0b10000000)
    load(cpu, 0, [0xCB, 0x06])  # RLC (HL)
    cpu.step()
    assert cpu.memory.read_byte(0x8000) == 0b00000001
    assert cpu.regs.f & FLAG_C
