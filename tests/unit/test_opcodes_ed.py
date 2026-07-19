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


def test_sbc_hl_bc_sets_carry_on_borrow():
    cpu = make_cpu()
    cpu.regs.hl = 0x0000
    cpu.regs.bc = 0x0001
    load(cpu, 0, [0xED, 0x42])  # SBC HL,BC
    cpu.step()
    assert cpu.regs.hl == 0xFFFF
    assert cpu.regs.f & FLAG_C


def test_adc_hl_bc_includes_incoming_carry():
    cpu = make_cpu()
    cpu.regs.hl = 0x0001
    cpu.regs.bc = 0x0001
    cpu.regs.f = FLAG_C
    load(cpu, 0, [0xED, 0x4A])  # ADC HL,BC
    cpu.step()
    assert cpu.regs.hl == 0x0003


def test_ld_nnnn_bc_and_ld_bc_nnnn_round_trip():
    cpu = make_cpu()
    cpu.regs.bc = 0x1234
    load(cpu, 0, [0xED, 0x43, 0x00, 0x80])  # LD (0x8000),BC
    cpu.step()
    cpu.regs.bc = 0
    load(cpu, 4, [0xED, 0x4B, 0x00, 0x80])  # LD BC,(0x8000)
    cpu.step()
    assert cpu.regs.bc == 0x1234


def test_neg_negates_a_and_sets_carry_unless_zero():
    cpu = make_cpu()
    cpu.regs.a = 0x01
    load(cpu, 0, [0xED, 0x44])  # NEG
    cpu.step()
    assert cpu.regs.a == 0xFF
    assert cpu.regs.f & FLAG_C
    assert cpu.regs.f & FLAG_N


def test_neg_of_zero_clears_carry():
    cpu = make_cpu()
    cpu.regs.a = 0x00
    load(cpu, 0, [0xED, 0x4C])  # NEG (undocumented duplicate slot)
    cpu.step()
    assert cpu.regs.a == 0x00
    assert not (cpu.regs.f & FLAG_C)
    assert cpu.regs.f & FLAG_Z


def test_retn_restores_iff1_from_iff2():
    cpu = make_cpu()
    cpu.regs.sp = 0xFFF0
    cpu.regs.iff2 = True
    cpu.push_word(0x1234)
    load(cpu, 0, [0xED, 0x45])  # RETN
    cpu.step()
    assert cpu.regs.pc == 0x1234
    assert cpu.regs.iff1 is True


def test_im_modes():
    cpu = make_cpu()
    load(cpu, 0, [0xED, 0x46])  # IM 0
    cpu.step()
    assert cpu.regs.im == 0
    load(cpu, 2, [0xED, 0x56])  # IM 1
    cpu.step()
    assert cpu.regs.im == 1
    load(cpu, 4, [0xED, 0x5E])  # IM 2
    cpu.step()
    assert cpu.regs.im == 2


def test_ld_a_i_sets_pv_from_iff2():
    cpu = make_cpu()
    cpu.regs.i = 0x80
    cpu.regs.iff2 = True
    load(cpu, 0, [0xED, 0x57])  # LD A,I
    cpu.step()
    assert cpu.regs.a == 0x80
    assert cpu.regs.f & FLAG_S
    assert cpu.regs.f & FLAG_P


def test_ld_i_a_and_ld_r_a():
    cpu = make_cpu()
    cpu.regs.a = 0x42
    load(cpu, 0, [0xED, 0x47])  # LD I,A
    cpu.step()
    assert cpu.regs.i == 0x42
    load(cpu, 2, [0xED, 0x4F])  # LD R,A
    cpu.step()
    assert cpu.regs.r == 0x42


def test_rrd_rotates_nibbles_between_a_and_memory():
    cpu = make_cpu()
    cpu.regs.a = 0x12
    cpu.regs.hl = 0x8000
    cpu.memory.write_byte(0x8000, 0x34)
    load(cpu, 0, [0xED, 0x67])  # RRD
    cpu.step()
    assert cpu.regs.a == 0x14
    assert cpu.memory.read_byte(0x8000) == 0x23


def test_rld_rotates_nibbles_the_other_way():
    cpu = make_cpu()
    cpu.regs.a = 0x12
    cpu.regs.hl = 0x8000
    cpu.memory.write_byte(0x8000, 0x34)
    load(cpu, 0, [0xED, 0x6F])  # RLD
    cpu.step()
    assert cpu.regs.a == 0x13
    assert cpu.memory.read_byte(0x8000) == 0x42


def test_ldi_copies_byte_and_updates_pointers_and_counter():
    cpu = make_cpu()
    cpu.regs.hl = 0x8000
    cpu.regs.de = 0x9000
    cpu.regs.bc = 0x0002
    cpu.memory.write_byte(0x8000, 0x99)
    load(cpu, 0, [0xED, 0xA0])  # LDI
    cpu.step()
    assert cpu.memory.read_byte(0x9000) == 0x99
    assert cpu.regs.hl == 0x8001
    assert cpu.regs.de == 0x9001
    assert cpu.regs.bc == 0x0001
    assert cpu.regs.f & FLAG_P  # BC != 0


def test_ldir_repeats_until_bc_zero():
    # LDIR completes its whole repeat count within a single step() call
    # (looped internally for interpreter speed -- see the comment in
    # instructions/blockio.py's _block_copy), not by re-dispatching per iteration.
    cpu = make_cpu()
    cpu.regs.hl = 0x8000
    cpu.regs.de = 0x9000
    cpu.regs.bc = 0x0003
    cpu.memory.write_byte(0x8000, 0x01)
    cpu.memory.write_byte(0x8001, 0x02)
    cpu.memory.write_byte(0x8002, 0x03)
    load(cpu, 0, [0xED, 0xB0])  # LDIR
    cpu.step()
    assert cpu.regs.bc == 0
    assert [cpu.memory.read_byte(a) for a in (0x9000, 0x9001, 0x9002)] == [1, 2, 3]
    assert cpu.regs.pc == 0x0002  # moved past LDIR once BC hit zero


def test_cpi_sets_zero_when_match_found():
    cpu = make_cpu()
    cpu.regs.a = 0x42
    cpu.regs.hl = 0x8000
    cpu.regs.bc = 0x0001
    cpu.memory.write_byte(0x8000, 0x42)
    load(cpu, 0, [0xED, 0xA1])  # CPI
    cpu.step()
    assert cpu.regs.f & FLAG_Z
    assert cpu.regs.a == 0x42  # A unchanged
    assert cpu.regs.hl == 0x8001


def test_cpir_stops_early_on_match():
    cpu = make_cpu()
    cpu.regs.a = 0x05
    cpu.regs.hl = 0x8000
    cpu.regs.bc = 0x0005
    cpu.memory.write_byte(0x8000, 0x01)
    cpu.memory.write_byte(0x8001, 0x05)
    load(cpu, 0, [0xED, 0xB1])  # CPIR
    cpu.step()  # searches internally, stops as soon as it matches at 0x8001
    assert cpu.regs.f & FLAG_Z
    assert cpu.regs.pc == 0x0002
    assert cpu.regs.bc == 3
    assert cpu.regs.hl == 0x8002


def test_in_r_c_sets_flags_from_value():
    cpu = make_cpu()
    cpu.io_read = lambda port: 0x00
    cpu.regs.bc = 0x1234
    load(cpu, 0, [0xED, 0x40])  # IN B,(C)
    cpu.step()
    assert cpu.regs.b == 0x00
    assert cpu.regs.f & FLAG_Z


def test_out_c_r_calls_io_write_with_bc_port():
    cpu = make_cpu()
    calls = []
    cpu.io_write = lambda port, value: calls.append((port, value))
    cpu.regs.b = 0x99
    cpu.regs.c = 0x34
    load(cpu, 0, [0xED, 0x41])  # OUT (C),B
    cpu.step()
    assert calls == [(0x9934, 0x99)]


def test_undocumented_ed_byte_is_a_safe_nop():
    cpu = make_cpu()
    load(cpu, 0, [0xED, 0x00])  # not a documented ED opcode
    cpu.step()
    assert cpu.regs.pc == 0x0002
