from zxemu_core.cpu.registers import FLAG_C, FLAG_H, FLAG_N, FLAG_P, FLAG_S, FLAG_X, FLAG_Y, FLAG_Z
from zxemu_core.cpu.z80 import Z80
from zxemu_core.memory import Bank, Memory


def make_cpu() -> Z80:
    memory = Memory([Bank(), Bank(), Bank(), Bank()])
    cpu = Z80(memory)
    cpu.reset()
    return cpu


def load(cpu: Z80, address: int, data: bytes) -> None:
    for offset, byte in enumerate(data):
        cpu.memory.write_byte(address + offset, byte)


def run(cpu: Z80, steps: int = 1) -> int:
    total = 0
    for _ in range(steps):
        total += cpu.step()
    return total


# --- NOP / LD r,r' -----------------------------------------------------------

def test_nop_does_nothing_but_advance_pc():
    cpu = make_cpu()
    load(cpu, 0, [0x00])
    t = run(cpu)
    assert cpu.regs.pc == 1
    assert t == 4


def test_ld_r_r_copies_register():
    cpu = make_cpu()
    cpu.regs.b = 0x99
    load(cpu, 0, [0x41])  # LD B,C  (dest=B index0, src=C index1) -> wait: 0x41 = LD B,C? check below
    run(cpu)
    # 0x41: dest=(0x41>>3)&7=0 (B), src=0x41&7=1 (C) => LD B,C
    assert cpu.regs.b == cpu.regs.c


def test_ld_r_hl_reads_memory():
    cpu = make_cpu()
    cpu.regs.hl = 0x8000
    cpu.memory.write_byte(0x8000, 0x77)
    load(cpu, 0, [0x46])  # LD B,(HL)
    run(cpu)
    assert cpu.regs.b == 0x77


def test_ld_hl_r_writes_memory():
    cpu = make_cpu()
    cpu.regs.hl = 0x8000
    cpu.regs.a = 0x55
    load(cpu, 0, [0x77])  # LD (HL),A
    run(cpu)
    assert cpu.memory.read_byte(0x8000) == 0x55


def test_halt_parks_pc_past_instruction_and_holds():
    cpu = make_cpu()
    load(cpu, 0, [0x76])
    run(cpu)
    assert cpu.halted is True
    assert cpu.regs.pc == 1  # PC sits just past the HALT, not on it
    run(cpu)  # still halted: burns an idle cycle, PC does not advance
    assert cpu.halted is True
    assert cpu.regs.pc == 1


# --- LD r,n / 16-bit LD rr,nnnn -----------------------------------------------

def test_ld_r_n_immediate():
    cpu = make_cpu()
    load(cpu, 0, [0x3E, 0x42])  # LD A,0x42
    run(cpu)
    assert cpu.regs.a == 0x42
    assert cpu.regs.pc == 2


def test_ld_rr_nnnn():
    cpu = make_cpu()
    load(cpu, 0, [0x21, 0xCD, 0xAB])  # LD HL,0xABCD
    run(cpu)
    assert cpu.regs.hl == 0xABCD


# --- INC/DEC r and (HL) --------------------------------------------------

def test_inc_r_sets_zero_flag_on_wrap():
    cpu = make_cpu()
    cpu.regs.b = 0xFF
    load(cpu, 0, [0x04])  # INC B
    run(cpu)
    assert cpu.regs.b == 0x00
    assert cpu.regs.f & FLAG_Z
    assert cpu.regs.f & FLAG_H


def test_inc_r_sets_overflow_at_0x7f():
    cpu = make_cpu()
    cpu.regs.a = 0x7F
    load(cpu, 0, [0x3C])  # INC A
    run(cpu)
    assert cpu.regs.a == 0x80
    assert cpu.regs.f & FLAG_P
    assert cpu.regs.f & FLAG_S


def test_dec_r_preserves_carry_flag():
    cpu = make_cpu()
    cpu.regs.f = FLAG_C
    cpu.regs.b = 0x01
    load(cpu, 0, [0x05])  # DEC B
    run(cpu)
    assert cpu.regs.b == 0x00
    assert cpu.regs.f & FLAG_Z
    assert cpu.regs.f & FLAG_C  # untouched by INC/DEC


def test_inc_dec_hl_indirect():
    cpu = make_cpu()
    cpu.regs.hl = 0x8000
    cpu.memory.write_byte(0x8000, 0x0F)
    load(cpu, 0, [0x34])  # INC (HL)
    run(cpu)
    assert cpu.memory.read_byte(0x8000) == 0x10


# --- ALU register + immediate forms -----------------------------------------

def test_add_a_r_sets_carry_and_half_carry():
    cpu = make_cpu()
    cpu.regs.a = 0xFF
    cpu.regs.b = 0x01
    load(cpu, 0, [0x80])  # ADD A,B
    run(cpu)
    assert cpu.regs.a == 0x00
    assert cpu.regs.f & FLAG_C
    assert cpu.regs.f & FLAG_H
    assert cpu.regs.f & FLAG_Z


def test_adc_a_r_includes_carry_in():
    cpu = make_cpu()
    cpu.regs.a = 0x01
    cpu.regs.b = 0x01
    cpu.regs.f = FLAG_C
    load(cpu, 0, [0x88])  # ADC A,B
    run(cpu)
    assert cpu.regs.a == 0x03


def test_sub_a_n_immediate():
    cpu = make_cpu()
    cpu.regs.a = 0x10
    load(cpu, 0, [0xD6, 0x01])  # SUB 0x01
    run(cpu)
    assert cpu.regs.a == 0x0F
    assert cpu.regs.f & FLAG_N


def test_and_a_r_sets_half_carry_and_parity():
    cpu = make_cpu()
    cpu.regs.a = 0xFF
    cpu.regs.b = 0x0F
    load(cpu, 0, [0xA0])  # AND B
    run(cpu)
    assert cpu.regs.a == 0x0F
    assert cpu.regs.f & FLAG_H
    assert cpu.regs.f & FLAG_P  # 0x0F has even parity


def test_xor_a_a_zeroes_and_sets_zero_flag():
    cpu = make_cpu()
    cpu.regs.a = 0x77
    load(cpu, 0, [0xAF])  # XOR A
    run(cpu)
    assert cpu.regs.a == 0x00
    assert cpu.regs.f & FLAG_Z
    assert cpu.regs.f & FLAG_P


def test_cp_does_not_change_a_but_sets_flags():
    cpu = make_cpu()
    cpu.regs.a = 0x05
    load(cpu, 0, [0xFE, 0x05])  # CP 0x05
    run(cpu)
    assert cpu.regs.a == 0x05
    assert cpu.regs.f & FLAG_Z


def test_cp_undocumented_flags_come_from_operand():
    cpu = make_cpu()
    cpu.regs.a = 0x00
    load(cpu, 0, [0xFE, 0x28])  # CP 0x28 -> bit5(Y) set in operand, bit3(X) clear
    run(cpu)
    assert bool(cpu.regs.f & FLAG_Y) == bool(0x28 & FLAG_Y)
    assert bool(cpu.regs.f & FLAG_X) == bool(0x28 & FLAG_X)


# --- 16-bit ADD HL,rr / INC rr / DEC rr --------------------------------------

def test_add_hl_rr_sets_half_carry_and_carry():
    cpu = make_cpu()
    cpu.regs.hl = 0xFFFF
    cpu.regs.bc = 0x0001
    load(cpu, 0, [0x09])  # ADD HL,BC
    run(cpu)
    assert cpu.regs.hl == 0x0000
    assert cpu.regs.f & FLAG_C
    assert cpu.regs.f & FLAG_H


def test_inc_dec_16_bit_wrap():
    cpu = make_cpu()
    cpu.regs.bc = 0xFFFF
    load(cpu, 0, [0x03])  # INC BC
    run(cpu)
    assert cpu.regs.bc == 0x0000


# --- PUSH/POP -----------------------------------------------------------

def test_push_pop_bc_round_trip():
    cpu = make_cpu()
    cpu.regs.sp = 0xFFF0
    cpu.regs.bc = 0x1234
    load(cpu, 0, [0xC5])  # PUSH BC
    run(cpu)
    cpu.regs.bc = 0x0000
    load(cpu, 1, [0xC1])  # POP BC
    run(cpu)
    assert cpu.regs.bc == 0x1234


# --- Jumps / calls / returns --------------------------------------------

def test_jp_nnnn():
    cpu = make_cpu()
    load(cpu, 0, [0xC3, 0x00, 0x80])  # JP 0x8000
    run(cpu)
    assert cpu.regs.pc == 0x8000


def test_jr_offset_forward():
    cpu = make_cpu()
    load(cpu, 0, [0x18, 0x05])  # JR +5
    run(cpu)
    assert cpu.regs.pc == 0x0007  # 2 (after instr) + 5


def test_jr_nz_not_taken_when_zero_set():
    cpu = make_cpu()
    cpu.regs.f = FLAG_Z
    load(cpu, 0, [0x20, 0x05])  # JR NZ,+5
    run(cpu)
    assert cpu.regs.pc == 0x0002


def test_djnz_loops_until_b_zero():
    cpu = make_cpu()
    cpu.regs.b = 0x03
    load(cpu, 0, [0x10, 0xFE])  # DJNZ $ (loop on itself)
    run(cpu)  # b=2, taken
    assert cpu.regs.pc == 0x0000
    run(cpu)  # b=1, taken
    assert cpu.regs.pc == 0x0000
    run(cpu)  # b=0, not taken
    assert cpu.regs.pc == 0x0002
    assert cpu.regs.b == 0


def test_call_and_ret_round_trip():
    cpu = make_cpu()
    cpu.regs.sp = 0xFFF0
    load(cpu, 0, [0xCD, 0x00, 0x80])  # CALL 0x8000
    load(cpu, 0x8000, [0xC9])  # RET
    run(cpu)  # CALL
    assert cpu.regs.pc == 0x8000
    run(cpu)  # RET
    assert cpu.regs.pc == 0x0003
    assert cpu.regs.sp == 0xFFF0


def test_call_cc_not_taken_skips_push():
    cpu = make_cpu()
    cpu.regs.sp = 0xFFF0
    cpu.regs.f = FLAG_Z
    load(cpu, 0, [0xC4, 0x00, 0x80])  # CALL NZ,0x8000 -- Z set, not taken
    run(cpu)
    assert cpu.regs.pc == 0x0003
    assert cpu.regs.sp == 0xFFF0


def test_rst_pushes_return_address_and_jumps():
    cpu = make_cpu()
    cpu.regs.sp = 0xFFF0
    load(cpu, 0, [0xEF])  # RST 28h
    run(cpu)
    assert cpu.regs.pc == 0x0028
    assert cpu.regs.sp == 0xFFEE


# --- Exchanges -----------------------------------------------------------

def test_ex_de_hl_swaps():
    cpu = make_cpu()
    cpu.regs.de = 0x1111
    cpu.regs.hl = 0x2222
    load(cpu, 0, [0xEB])
    run(cpu)
    assert cpu.regs.de == 0x2222
    assert cpu.regs.hl == 0x1111


def test_exx_swaps_bc_de_hl_with_shadow():
    cpu = make_cpu()
    cpu.regs.bc, cpu.regs.de, cpu.regs.hl = 0x1111, 0x2222, 0x3333
    cpu.regs.bc2, cpu.regs.de2, cpu.regs.hl2 = 0xAAAA, 0xBBBB, 0xCCCC
    load(cpu, 0, [0xD9])
    run(cpu)
    assert (cpu.regs.bc, cpu.regs.de, cpu.regs.hl) == (0xAAAA, 0xBBBB, 0xCCCC)


def test_ex_sp_hl_swaps_top_of_stack():
    cpu = make_cpu()
    cpu.regs.sp = 0x8000
    cpu.memory.write_word(0x8000, 0x1234)
    cpu.regs.hl = 0x5678
    load(cpu, 0, [0xE3])
    run(cpu)
    assert cpu.regs.hl == 0x1234
    assert cpu.memory.read_word(0x8000) == 0x5678


# --- Misc: DAA / CPL / SCF / CCF / rotates -----------------------------------

def test_daa_after_bcd_addition():
    cpu = make_cpu()
    cpu.regs.a = 0x09
    load(cpu, 0, [0xC6, 0x08])  # ADD A,0x08 -> 0x11 with half-carry
    run(cpu)
    load(cpu, 2, [0x27])  # DAA
    run(cpu)
    assert cpu.regs.a == 0x17  # BCD-correct result of 09 + 08 = 17


def test_cpl_inverts_a_and_sets_h_n():
    cpu = make_cpu()
    cpu.regs.a = 0b10110010
    load(cpu, 0, [0x2F])
    run(cpu)
    assert cpu.regs.a == 0b01001101
    assert cpu.regs.f & FLAG_H
    assert cpu.regs.f & FLAG_N


def test_scf_sets_carry_clears_h_n():
    cpu = make_cpu()
    cpu.regs.f = FLAG_H | FLAG_N | FLAG_Z
    load(cpu, 0, [0x37])
    run(cpu)
    assert cpu.regs.f & FLAG_C
    assert not (cpu.regs.f & FLAG_H)
    assert not (cpu.regs.f & FLAG_N)
    assert cpu.regs.f & FLAG_Z  # untouched


def test_ccf_inverts_carry():
    cpu = make_cpu()
    cpu.regs.f = FLAG_C
    load(cpu, 0, [0x3F])
    run(cpu)
    assert not (cpu.regs.f & FLAG_C)


def test_rlca_rotates_bit7_into_carry_and_bit0():
    cpu = make_cpu()
    cpu.regs.a = 0b10000001
    load(cpu, 0, [0x07])
    run(cpu)
    assert cpu.regs.a == 0b00000011
    assert cpu.regs.f & FLAG_C


# --- memory-indirect A loads --------------------------------------------

def test_ld_bc_a_and_ld_a_bc_round_trip():
    cpu = make_cpu()
    cpu.regs.bc = 0x8000
    cpu.regs.a = 0x99
    load(cpu, 0, [0x02])  # LD (BC),A
    run(cpu)
    cpu.regs.a = 0
    load(cpu, 1, [0x0A])  # LD A,(BC)
    run(cpu)
    assert cpu.regs.a == 0x99


def test_ld_nn_a_and_ld_a_nn():
    cpu = make_cpu()
    cpu.regs.a = 0x55
    load(cpu, 0, [0x32, 0x00, 0x80])  # LD (0x8000),A
    run(cpu)
    cpu.regs.a = 0
    load(cpu, 3, [0x3A, 0x00, 0x80])  # LD A,(0x8000)
    run(cpu)
    assert cpu.regs.a == 0x55


# --- IO stubs (default floating bus, overridden later by machine.py) --------

def test_in_a_n_uses_default_floating_bus_stub():
    cpu = make_cpu()
    load(cpu, 0, [0xDB, 0x1F])  # IN A,(0x1F)
    run(cpu)
    assert cpu.regs.a == 0xFF


def test_out_n_a_calls_io_write_hook():
    cpu = make_cpu()
    calls = []
    cpu.io_write = lambda port, value: calls.append((port, value))
    cpu.regs.a = 0x42
    load(cpu, 0, [0xD3, 0x10])  # OUT (0x10),A
    run(cpu)
    assert calls == [((0x42 << 8) | 0x10, 0x42)]


def test_all_prefix_bytes_are_now_wired_up():
    # CB/ED/DD/FD are fully implemented in their own opcode tables (see
    # test_opcodes_cb.py / test_opcodes_ed.py / test_opcodes_indexed.py);
    # this just confirms none of them raise NotImplementedError on their own.
    for opcode, follow_up in ((0xCB, 0x00), (0xDD, 0x00), (0xED, 0x00), (0xFD, 0x00)):
        cpu = make_cpu()
        load(cpu, 0, [opcode, follow_up])
        run(cpu)
