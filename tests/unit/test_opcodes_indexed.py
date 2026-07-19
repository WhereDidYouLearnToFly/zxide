from zxemu_core.cpu.registers import FLAG_C, FLAG_Z
from zxemu_core.cpu.z80 import Z80
from zxemu_core.memory import Bank, Memory


def make_cpu() -> Z80:
    cpu = Z80(Memory([Bank(), Bank(), Bank(), Bank()]))
    cpu.reset()
    return cpu


def load(cpu: Z80, address: int, data: bytes) -> None:
    for offset, byte in enumerate(data):
        cpu.memory.write_byte(address + offset, byte & 0xFF)


def test_ld_ix_nnnn():
    cpu = make_cpu()
    load(cpu, 0, [0xDD, 0x21, 0xCD, 0xAB])  # LD IX,0xABCD
    cpu.step()
    assert cpu.regs.ix == 0xABCD


def test_ld_iy_nnnn_independent_of_ix():
    cpu = make_cpu()
    cpu.regs.ix = 0x1111
    load(cpu, 0, [0xFD, 0x21, 0x22, 0x22])  # LD IY,0x2222
    cpu.step()
    assert cpu.regs.iy == 0x2222
    assert cpu.regs.ix == 0x1111


def test_inc_dec_ix():
    cpu = make_cpu()
    cpu.regs.ix = 0x00FF
    load(cpu, 0, [0xDD, 0x23])  # INC IX
    cpu.step()
    assert cpu.regs.ix == 0x0100
    load(cpu, 2, [0xDD, 0x2B])  # DEC IX
    cpu.step()
    assert cpu.regs.ix == 0x00FF


def test_ld_mem_ix_plus_d_writes_at_displaced_address():
    cpu = make_cpu()
    cpu.regs.ix = 0x8000
    cpu.regs.a = 0x77
    load(cpu, 0, [0xDD, 0x77, 0x05])  # LD (IX+5),A
    cpu.step()
    assert cpu.memory.read_byte(0x8005) == 0x77


def test_ld_mem_ix_plus_negative_d():
    cpu = make_cpu()
    cpu.regs.ix = 0x8010
    cpu.regs.a = 0x42
    load(cpu, 0, [0xDD, 0x77, 0xFB])  # LD (IX-5),A  (0xFB = -5 signed)
    cpu.step()
    assert cpu.memory.read_byte(0x800B) == 0x42


def test_ld_r_from_mem_ix_plus_d():
    cpu = make_cpu()
    cpu.regs.ix = 0x8000
    cpu.memory.write_byte(0x8003, 0x99)
    load(cpu, 0, [0xDD, 0x46, 0x03])  # LD B,(IX+3)
    cpu.step()
    assert cpu.regs.b == 0x99


def test_ld_r_from_mem_ix_plus_d_does_not_use_ixh():
    # the OTHER operand alongside an (IX+d) access stays plain H, not IXH
    cpu = make_cpu()
    cpu.regs.ix = 0x8000
    cpu.regs.h = 0x11
    cpu.memory.write_byte(0x8000, 0x22)
    load(cpu, 0, [0xDD, 0x74, 0x00])  # LD (IX+0),H -> writes plain H (0x11), not IXH
    cpu.step()
    assert cpu.memory.read_byte(0x8000) == 0x11


def test_ld_ixh_undocumented_half_register():
    cpu = make_cpu()
    cpu.regs.ix = 0xABCD
    load(cpu, 0, [0xDD, 0x26, 0x99])  # LD IXH,0x99
    cpu.step()
    assert cpu.regs.ix == 0x99CD


def test_ld_b_ixh_undocumented():
    cpu = make_cpu()
    cpu.regs.ix = 0x5566
    load(cpu, 0, [0xDD, 0x44])  # LD B,IXH
    cpu.step()
    assert cpu.regs.b == 0x55


def test_add_ix_bc():
    cpu = make_cpu()
    cpu.regs.ix = 0x0001
    cpu.regs.bc = 0x0001
    load(cpu, 0, [0xDD, 0x09])  # ADD IX,BC
    cpu.step()
    assert cpu.regs.ix == 0x0002


def test_add_ix_ix_doubles():
    cpu = make_cpu()
    cpu.regs.ix = 0x1000
    load(cpu, 0, [0xDD, 0x29])  # ADD IX,IX
    cpu.step()
    assert cpu.regs.ix == 0x2000


def test_push_pop_iy():
    cpu = make_cpu()
    cpu.regs.sp = 0xFFF0
    cpu.regs.iy = 0x4321
    load(cpu, 0, [0xFD, 0xE5])  # PUSH IY
    cpu.step()
    cpu.regs.iy = 0
    load(cpu, 2, [0xFD, 0xE1])  # POP IY
    cpu.step()
    assert cpu.regs.iy == 0x4321


def test_jp_ix_jumps_to_register_value_not_indirect():
    cpu = make_cpu()
    cpu.regs.ix = 0x9000
    load(cpu, 0, [0xDD, 0xE9])  # JP (IX)
    cpu.step()
    assert cpu.regs.pc == 0x9000


def test_ex_de_hl_unaffected_by_dd_prefix():
    # documented quirk: EX DE,HL has no indexed form; DD before it is wasted
    cpu = make_cpu()
    cpu.regs.de = 0x1111
    cpu.regs.hl = 0x2222
    load(cpu, 0, [0xDD, 0xEB])  # "DD EX DE,HL" -- prefix wasted, plain EX DE,HL runs
    cpu.step()
    assert cpu.regs.de == 0x2222
    assert cpu.regs.hl == 0x1111


def test_unaffected_opcode_falls_back_to_base_and_consumes_extra_prefix_time():
    cpu = make_cpu()
    load(cpu, 0, [0xDD, 0x00])  # "DD NOP" -- prefix wasted
    t = cpu.step()
    assert cpu.regs.pc == 0x0002
    assert t == 8  # 4 (DD fetch) + 4 (NOP fetch), no further cost


def test_prefix_stacking_last_one_wins():
    cpu = make_cpu()
    cpu.regs.ix = 0x1111
    cpu.regs.iy = 0x2222
    load(cpu, 0, [0xDD, 0xFD, 0x21, 0x00, 0x30])  # DD FD LD ?,0x3000 -> last prefix (FD) wins -> LD IY,0x3000
    cpu.step()
    assert cpu.regs.iy == 0x3000
    assert cpu.regs.ix == 0x1111


def test_dd_ed_drops_index_prefix_and_runs_ed_instruction():
    cpu = make_cpu()
    cpu.regs.a = 0x01
    load(cpu, 0, [0xDD, 0xED, 0x44])  # DD then ED NEG -- DD wasted, NEG runs normally
    cpu.step()
    assert cpu.regs.a == 0xFF


# --- DDCB/FDCB: bit ops on (IX+d)/(IY+d) -------------------------------------


def test_ddcb_rlc_writes_memory_and_copies_to_register():
    cpu = make_cpu()
    cpu.regs.ix = 0x8000
    cpu.memory.write_byte(0x8002, 0b10000001)
    load(cpu, 0, [0xDD, 0xCB, 0x02, 0x00])  # RLC (IX+2),B (undocumented copy target)
    cpu.step()
    assert cpu.memory.read_byte(0x8002) == 0b00000011
    assert cpu.regs.b == 0b00000011  # copied
    assert cpu.regs.f & FLAG_C


def test_ddcb_rlc_with_target_6_only_writes_memory():
    cpu = make_cpu()
    cpu.regs.ix = 0x8000
    cpu.regs.b = 0xAA  # sentinel, must remain untouched
    cpu.memory.write_byte(0x8002, 0b10000001)
    load(cpu, 0, [0xDD, 0xCB, 0x02, 0x06])  # RLC (IX+2)  (target field = 6, no register copy)
    cpu.step()
    assert cpu.memory.read_byte(0x8002) == 0b00000011
    assert cpu.regs.b == 0xAA


def test_ddcb_bit_tests_memory_without_writing():
    cpu = make_cpu()
    cpu.regs.ix = 0x8000
    cpu.memory.write_byte(0x8001, 0x00)
    load(cpu, 0, [0xDD, 0xCB, 0x01, 0x46])  # BIT 0,(IX+1)
    cpu.step()
    assert cpu.regs.f & FLAG_Z
    assert cpu.memory.read_byte(0x8001) == 0x00


def test_ddcb_res_clears_bit_and_copies_to_register():
    cpu = make_cpu()
    cpu.regs.iy = 0x8000
    cpu.memory.write_byte(0x8000, 0xFF)
    load(cpu, 0, [0xFD, 0xCB, 0x00, 0x87])  # RES 0,(IY+0),A
    cpu.step()
    assert cpu.memory.read_byte(0x8000) == 0xFE
    assert cpu.regs.a == 0xFE


def test_ddcb_set_sets_bit():
    cpu = make_cpu()
    cpu.regs.ix = 0x8000
    cpu.memory.write_byte(0x8000, 0x00)
    load(cpu, 0, [0xDD, 0xCB, 0x00, 0xC6])  # SET 0,(IX+0)
    cpu.step()
    assert cpu.memory.read_byte(0x8000) == 0x01


def test_ddcb_negative_displacement():
    cpu = make_cpu()
    cpu.regs.ix = 0x8010
    cpu.memory.write_byte(0x800B, 0x00)
    load(cpu, 0, [0xDD, 0xCB, 0xFB, 0xC6])  # SET 0,(IX-5)
    cpu.step()
    assert cpu.memory.read_byte(0x800B) == 0x01
