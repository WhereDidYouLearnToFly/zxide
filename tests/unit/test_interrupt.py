from zxemu_core.cpu.z80 import Z80
from zxemu_core.memory import Bank, Memory


def make_cpu() -> Z80:
    cpu = Z80(Memory([Bank(), Bank(), Bank(), Bank()]))
    cpu.reset()
    return cpu


def test_interrupt_masked_when_iff1_disabled():
    cpu = make_cpu()
    cpu.regs.iff1 = False
    cpu.regs.pc = 0x1234
    t = cpu.maskable_interrupt()
    assert t == 0
    assert cpu.regs.pc == 0x1234


def test_im1_pushes_pc_and_jumps_to_0038():
    cpu = make_cpu()
    cpu.regs.iff1 = True
    cpu.regs.iff2 = True
    cpu.regs.im = 1
    cpu.regs.sp = 0xFFF0
    cpu.regs.pc = 0x5678
    t = cpu.maskable_interrupt()
    assert cpu.regs.pc == 0x0038
    assert cpu.regs.sp == 0xFFEE
    assert cpu.pop_word() == 0x5678
    assert t == 13
    assert cpu.regs.iff1 is False
    assert cpu.regs.iff2 is False


def test_interrupt_wakes_a_halted_cpu():
    cpu = make_cpu()
    cpu.memory.write_byte(0x0000, 0x76)  # HALT
    cpu.regs.iff1 = True
    cpu.regs.im = 1
    cpu.regs.sp = 0xFFF0
    cpu.step()
    assert cpu.halted is True
    cpu.maskable_interrupt()
    assert cpu.halted is False
    assert cpu.regs.pc == 0x0038
    # The pushed return address must be PAST the HALT (0x0001), so execution
    # resumes after it -- not on the HALT, which would re-halt forever.
    assert cpu.pop_word() == 0x0001


def test_halted_cpu_resumes_after_halt_when_interrupt_returns():
    # End-to-end: HALT at 0x0000, an ISR at 0x0038 that just RETurns, and a
    # NOP at 0x0001. After the interrupt the CPU must execute the NOP, proving
    # it escaped the HALT rather than re-halting.
    cpu = make_cpu()
    cpu.memory.write_byte(0x0000, 0x76)  # HALT
    cpu.memory.write_byte(0x0001, 0x3C)  # INC A (a visible side effect past the HALT)
    cpu.memory.write_byte(0x0038, 0xC9)  # RET (minimal IM1 handler)
    cpu.regs.iff1 = True
    cpu.regs.im = 1
    cpu.regs.sp = 0xFFF0
    cpu.regs.a = 0

    cpu.step()  # HALT
    assert cpu.halted is True
    cpu.maskable_interrupt()  # jump to 0x0038
    cpu.step()  # RET -> back to 0x0001
    assert cpu.regs.pc == 0x0001
    cpu.step()  # INC A
    assert cpu.regs.a == 1  # executed the instruction after HALT


def test_im2_uses_vector_table():
    cpu = make_cpu()
    cpu.regs.iff1 = True
    cpu.regs.im = 2
    cpu.regs.i = 0x80
    cpu.regs.sp = 0xFFF0
    cpu.regs.pc = 0x1000
    vector_addr = (0x80 << 8) | 0xFF
    cpu.memory.write_byte(vector_addr, 0x00)
    cpu.memory.write_byte((vector_addr + 1) & 0xFFFF, 0x90)
    t = cpu.maskable_interrupt()
    assert cpu.regs.pc == 0x9000
    assert t == 19
