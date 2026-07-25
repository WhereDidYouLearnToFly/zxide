"""Dump a machine's memory, assemble it for real, and compare the bytes.

This is the test the whole dumper is arranged around. Everything else checks that our
code agrees with our code; this one hands the output to **sjasmplus** and asks whether
the source actually reproduces the program it came from. Byte-identical means the dump
provably represents the machine — and it is what makes promoting a region from bytes to
disassembly a safe thing to do, because the promotion is checkable by exactly this test.

The raw ``.bin`` is what gets compared, not the ``.sna``: a snapshot carries a header and,
on 48K, keeps PC on the stack, so it is not a plain memory image. The project emits both --
the image to check against, the snapshot to run.

The snapshot is written by a Lua block in the generated source rather than by ``savesna``,
because ``savesna`` defaults every register. That mattered in practice: a rebuilt game came
up with a white border and a dead keyboard, both because an **IM 2** handler never fired.

Skipped without sjasmplus on PATH, following ``test_asset_pipeline.py``.
"""

from __future__ import annotations

import importlib.resources as res
import json
import shutil
import subprocess

import pytest

from zxemu_core.debug import dumper
from zxemu_core.machine import Machine
from zxemu_ui.workspace.dump_project import IMAGE_NAME, dump_to_project

pytestmark = pytest.mark.skipif(shutil.which("sjasmplus") is None,
                                reason="sjasmplus not on PATH")

RAM_SIZE = dumper.ADDRESS_SPACE - dumper.RAM_BASE


def _booted_48k() -> Machine:
    rom = (res.files("zxemu_core") / "roms" / "48.rom").read_bytes()
    machine = Machine(rom)
    for _ in range(150):
        machine.run_frame()
    return machine


def _ram_of(machine) -> bytes:
    return bytes(machine.memory.read_byte(a)
                 for a in range(dumper.RAM_BASE, dumper.ADDRESS_SPACE))


def _rebuilt_matches(folder, machine) -> None:
    """The rebuild must be byte-identical to the memory it came from. No exceptions.

    It can be absolute again because the machine state is restored by *writing the
    snapshot correctly* (a Lua block in the generated source) rather than by injecting
    Z80 restore code into the program. Nothing is added to RAM at all, so there is no
    "except these fifty bytes" clause to argue about.
    """
    assert (folder / IMAGE_NAME).read_bytes() == _ram_of(machine)


def _assemble(folder) -> None:
    result = subprocess.run(["sjasmplus", "main.asm"], cwd=folder,
                            capture_output=True, text=True)
    assert result.returncode == 0, f"sjasmplus failed:\n{result.stdout}\n{result.stderr}"


def _coverage_over(*runs) -> bytearray:
    executed = bytearray(dumper.ADDRESS_SPACE)
    for start, end in runs:
        for address in range(start, end):
            executed[address] = 1
    return executed


def test_an_all_data_dump_rebuilds_byte_identically(tmp_path):
    """The foundation. Nothing is disassembled, so this proves the plumbing alone:
    regions, ordering, org directives, incbin, and the manifest."""
    machine = _booted_48k()
    dump_to_project(machine, tmp_path, model="48k")

    _assemble(tmp_path)

    _rebuilt_matches(tmp_path, machine)


def test_a_dump_with_disassembled_code_rebuilds_byte_identically(tmp_path):
    """The one that matters. Real regions go through the disassembler and come back as
    text; if a single instruction were decoded to the wrong length or printed in a form
    sjasmplus encodes differently, every byte after it would shift and this would fail."""
    machine = _booted_48k()
    # The ROM's own code, copied into RAM, so the "executed" regions are genuine Z80
    # rather than the zeros a freshly booted RAM is full of.
    for offset in range(0x400):
        machine.memory.write_byte(0x8000 + offset, machine.memory.read_byte(0x0000 + offset))
    coverage = _coverage_over((0x8000, 0x8400))

    dump_to_project(machine, tmp_path, model="48k", coverage_executed=coverage)
    _assemble(tmp_path)

    _rebuilt_matches(tmp_path, machine)


def test_several_separate_code_regions_still_rebuild_exactly(tmp_path):
    """Region boundaries are where an off-by-one would hide, so exercise a few of them."""
    machine = _booted_48k()
    for base in (0x8000, 0x9000, 0xC000):
        for offset in range(0x200):
            machine.memory.write_byte(base + offset, machine.memory.read_byte(offset))
    coverage = _coverage_over((0x8000, 0x8200), (0x9000, 0x9200), (0xC000, 0xC200))

    dump_to_project(machine, tmp_path, model="48k", coverage_executed=coverage)
    _assemble(tmp_path)

    _rebuilt_matches(tmp_path, machine)


def test_the_dump_is_a_project_that_zxide_can_open(tmp_path):
    """The requirement, not a nicety: the output is somewhere you can work, so it carries
    a manifest naming the machine it came from and an entry point that builds."""
    machine = _booted_48k()
    coverage = _coverage_over((0x8000, 0x8100))

    project = dump_to_project(machine, tmp_path, model="48k",
                              coverage_executed=coverage, name="Dumped")

    manifest = json.loads((tmp_path / "zxide.json").read_text(encoding="utf-8"))
    assert manifest["model"] == "48k"          # or it reopens on the wrong machine
    assert manifest["main"] == "main.asm"
    assert project.model == "48k"
    assert (tmp_path / "main.asm").exists()
    assert list((tmp_path / "regions").glob("*.asm"))

    _assemble(tmp_path)
    assert (tmp_path / "main.sna").exists()    # ...and it runs, not just assembles


def test_banks_paged_out_at_dump_time_are_captured_too(tmp_path):
    """On real hardware this would need the machine halted and each bank paged in by hand.
    In an emulator a bank is a bytearray, readable whether or not it is mapped -- so all
    eight are captured, and the five that were invisible are 80K the address-space view
    would simply have missed."""
    from zxemu_ui.machine_factory import build_machine

    machine = build_machine("128k")
    for _ in range(200):
        machine.run_frame()
    # Leave a fingerprint in a bank that is *not* in the address space.
    hidden = 6
    for offset in range(16):
        machine.ram_banks[hidden].data[offset] = 0xA5

    dump_to_project(machine, tmp_path, model="128k")

    blob = tmp_path / "data" / f"bank{hidden}.bin"
    assert blob.exists(), "a paged-out bank was silently dropped"
    assert blob.read_bytes()[:16] == b"\xA5" * 16
    assert blob.read_bytes() == bytes(machine.ram_banks[hidden].data)
    # ...and the banks already visible are not duplicated: RAM5 and RAM2 never move, and
    # whichever bank slot 3 holds was captured through the address space with its coverage.
    visible = {5, 2, machine.paging_state().ram_bank}
    for number in visible:
        assert not (tmp_path / "data" / f"bank{number}.bin").exists()


def test_a_paged_out_bank_is_disassembled_where_it_was_seen_to_run(tmp_path):
    """The point of bank-aware coverage. Code runs in bank 3, the program pages bank 3
    away, and the dump still recovers it *as code* -- which is only possible because the
    bank was recorded at the moment it was mapped, not worked out afterwards."""
    from zxemu_ui.controller import EmulatorController
    from zxemu_ui.machine_factory import build_machine

    machine = build_machine("128k")
    controller = EmulatorController(machine)      # wires coverage to the paging listener
    controller.coverage.enabled = True

    machine.set_paging(0x03)
    routine = bytes([0x3E, 0x07, 0xD3, 0xFE, 0x00, 0x00, 0xC9])   # ld a,7 / out / nops / ret
    for offset, byte in enumerate(routine):
        machine.memory.write_byte(0xC000 + offset, byte)
    machine.cpu.regs.pc = 0xC000
    for _ in range(5):
        controller.coverage.mark(machine.cpu.regs.pc)
        machine.cpu.step()
    machine.set_paging(0x00)                      # ...and page it back out

    dump_to_project(machine, tmp_path, model="128k",
                    coverage_executed=controller.coverage.executed,
                    coverage=controller.coverage, start_address=0xC000)

    source = (tmp_path / "regions" / "bank3.asm").read_text(encoding="utf-8")
    assert "out ($FE),a" in source, "a paged-out bank was not disassembled"
    assert "SLOT 3" in source and "PAGE 3" in source
    _assemble(tmp_path)


def test_a_bank_that_never_ran_is_still_captured_as_data(tmp_path):
    """"Not yet", never "never": an unexercised bank comes out whole, just unclassified."""
    from zxemu_ui.controller import EmulatorController
    from zxemu_ui.machine_factory import build_machine

    machine = build_machine("128k")
    controller = EmulatorController(machine)
    controller.coverage.enabled = True
    for offset in range(8):
        machine.ram_banks[6].data[offset] = 0x5A

    dump_to_project(machine, tmp_path, model="128k",
                    coverage_executed=controller.coverage.executed,
                    coverage=controller.coverage)

    assert (tmp_path / "data" / "bank6.bin").read_bytes()[:8] == b"\x5A" * 8
    assert "incbin" in (tmp_path / "regions" / "bank6.asm").read_text(encoding="utf-8")


def test_a_paged_dump_restores_the_original_mapping_before_saving(tmp_path):
    """A bug that made the verification measure the wrong memory and pass anyway.

    Each bank's source ends with its own ``PAGE n`` in effect, and both SAVEBIN and
    SAVESNA write whatever is mapped *at that point*. Without putting the mapping back,
    the top 16K of the output is whichever bank happened to be included last -- so the
    byte-for-byte check compares against a bank the machine did not have mapped.
    """
    from zxemu_ui.machine_factory import build_machine

    machine = build_machine("128k")
    for _ in range(200):
        machine.run_frame()
    machine.set_paging(0x01)                     # bank 1 in slot 3, and it must stay there
    for offset in range(16):
        machine.memory.write_byte(0xC000 + offset, 0x3C)
    # A different, distinguishable pattern in a bank that will be included afterwards.
    for offset in range(16):
        machine.ram_banks[7].data[offset] = 0xE7

    dump_to_project(machine, tmp_path, model="128k")
    _assemble(tmp_path)

    image = (tmp_path / IMAGE_NAME).read_bytes()
    top = image[0xC000 - dumper.RAM_BASE:0xC000 - dumper.RAM_BASE + 16]
    assert top == b"\x3C" * 16, "the saved image has the wrong bank at 0xC000"
    _rebuilt_matches(tmp_path, machine)


def test_a_paged_model_dump_still_assembles(tmp_path):
    from zxemu_ui.machine_factory import build_machine

    machine = build_machine("128k")
    for _ in range(200):
        machine.run_frame()

    dump_to_project(machine, tmp_path, model="128k")
    _assemble(tmp_path)

    assert (tmp_path / "main.sna").exists()


def test_the_generated_source_says_what_it_cannot_know(tmp_path):
    """The two caveats that decide whether someone trusts the output belong in the file
    they will actually open, not only in the documentation."""
    dump_to_project(_booted_48k(), tmp_path, model="48k")

    main = (tmp_path / "main.asm").read_text(encoding="utf-8")

    assert "have not run yet" in main          # data may simply be unexercised code
    assert "resident" in main                  # only what was in memory is here


def test_the_rebuilt_snapshot_comes_back_with_the_machine_state(tmp_path):
    """A dump restores RAM; this restores everything that is *not* in RAM.

    The failure this prevents is the one a user hit: the rebuilt program ran, but with a
    white border and a dead keyboard. Both were the same cause -- ``savesna`` writes memory
    and an entry address and defaults every register, so a game reading keys from an
    **IM 2** interrupt handler came up with IM 1, the wrong ``I``, and interrupts disabled.
    It was alive and deaf.
    """
    from zxemu_core.storage.snapshot import load_sna
    from zxemu_ui.machine_factory import build_machine

    machine = _booted_48k()
    regs = machine.cpu.regs
    machine.ula.border_color = 2
    regs.i, regs.im = 0x39, 2
    regs.iff1 = regs.iff2 = True
    regs.sp = 0x7F00
    regs.bc, regs.de, regs.hl = 0x1234, 0x5678, 0x9ABC
    regs.bc2, regs.de2, regs.hl2 = 0x1111, 0x2222, 0x3333
    regs.a, regs.f, regs.a2, regs.f2 = 0x5A, 0x41, 0x77, 0x80
    regs.pc = 0x8000
    machine.memory.write_byte(0x8000, 0x18)      # jr $ -- park where it lands
    machine.memory.write_byte(0x8001, 0xFE)

    dump_to_project(machine, tmp_path, model="48k")
    _assemble(tmp_path)

    rebuilt = build_machine("48k")
    load_sna(rebuilt, (tmp_path / "main.sna").read_bytes())
    # No stub to run any more -- the snapshot carries the state -- but stepping a
    # little proves the machine is genuinely alive at the restored PC.
    for _ in range(300):
        rebuilt.cpu.step()

    new = rebuilt.cpu.regs
    assert rebuilt.ula.border_color == 2
    assert (new.i, new.im, new.iff1) == (0x39, 2, True)   # the keyboard's actual problem
    assert new.sp == 0x7F00
    assert (new.bc, new.de, new.hl) == (0x1234, 0x5678, 0x9ABC)
    assert (new.bc2, new.de2, new.hl2) == (0x1111, 0x2222, 0x3333)
    assert (new.a, new.f) == (0x5A, 0x41)
    # AF has no load instruction -- it can only be restored by popping, which is why the
    # stub borrows SP. Getting the pop offset wrong swaps AF and AF', silently.
    assert (new.a2, new.f2) == (0x77, 0x80)
    assert new.pc == 0x8000                       # ...and it resumed exactly where it was


def test_nothing_is_injected_into_the_program(tmp_path):
    """There is no restore stub any more, and that is the point.

    The machine state used to be restored by Z80 code planted in a run of zeros that
    coverage had not seen execute -- an inference, and a shaky one, since coverage means
    "not yet" and a big run of zeros is very often a buffer the program has not filled.
    Writing the snapshot correctly costs nothing instead, so the manifest declares no
    modification and the rebuild is exactly the original.
    """
    machine = _booted_48k()

    dump_to_project(machine, tmp_path, model="48k")

    manifest = json.loads((tmp_path / "zxide.json").read_text(encoding="utf-8"))
    assert manifest["dump"]["stub"] is None
    assert not (tmp_path / "regions" / "restore.asm").exists()
    _assemble(tmp_path)
    _rebuilt_matches(tmp_path, machine)
