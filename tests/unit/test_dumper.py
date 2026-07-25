"""Unit tests for the memory dumper's reasoning (zxemu_core.debug.dumper).

Everything here is about one property: **the dump must reassemble to exactly the bytes it
came from.** Proving that end to end needs an assembler, and that test lives in
``tests/integration/test_memory_dump.py``. What can be checked without one is the
structure underneath it -- that the regions tile memory exactly, that a disassembly
consumes precisely its region, and that a label is only ever used where it is also
defined. Each of those failing produces output that looks entirely reasonable and
rebuilds into a different program.
"""

import pytest

from zxemu_core.debug import dumper
from zxemu_core.debug.dumper import ADDRESS_SPACE, CODE, DATA, RAM_BASE, Region


class FakeMemory:
    """Just enough memory to disassemble: bytes from a base address, zero elsewhere."""

    def __init__(self, base: int = RAM_BASE, data: bytes = b""):
        self.base = base
        self.data = bytes(data)

    def read_byte(self, address: int) -> int:
        offset = address - self.base
        return self.data[offset] if 0 <= offset < len(self.data) else 0


def _coverage(*runs) -> bytearray:
    executed = bytearray(ADDRESS_SPACE)
    for start, end in runs:
        for address in range(start, end):
            executed[address] = 1
    return executed


# --- regions --------------------------------------------------------------------

def test_no_coverage_yields_one_data_region_covering_all_of_ram():
    """The all-data dump: correct, not yet useful, and a complete foundation."""
    regions = dumper.plan_regions(None)
    assert regions == [Region(RAM_BASE, ADDRESS_SPACE, DATA, "ram")]
    dumper.check_regions_tile(regions, RAM_BASE, ADDRESS_SPACE)


def test_executed_runs_become_code_between_data():
    regions = dumper.plan_regions(_coverage((0x8000, 0x8100)))
    assert [(r.start, r.end, r.kind) for r in regions] == [
        (RAM_BASE, 0x8000, DATA), (0x8000, 0x8100, CODE), (0x8100, ADDRESS_SPACE, DATA),
    ]
    dumper.check_regions_tile(regions, RAM_BASE, ADDRESS_SPACE)


def test_several_runs_all_survive():
    regions = dumper.plan_regions(_coverage((0x8000, 0x8100), (0x9000, 0x9040)))
    assert [r.kind for r in regions] == [DATA, CODE, DATA, CODE, DATA]
    dumper.check_regions_tile(regions, RAM_BASE, ADDRESS_SPACE)


def test_code_running_to_the_very_end_leaves_no_trailing_data():
    regions = dumper.plan_regions(_coverage((0xFF00, ADDRESS_SPACE)))
    assert regions[-1] == Region(0xFF00, ADDRESS_SPACE, CODE, "ram")
    dumper.check_regions_tile(regions, RAM_BASE, ADDRESS_SPACE)


def test_a_stray_executed_byte_is_left_as_data():
    """Coverage marks instruction starts, so a one-byte run is a computed jump landing in
    a table or a fluke -- not a routine. Carving two bytes of "code" out of a bitmap makes
    the dump worse, and data is always a safe answer."""
    regions = dumper.plan_regions(_coverage((0x9000, 0x9002)))
    assert [r.kind for r in regions] == [DATA]


def test_coverage_below_ram_is_ignored():
    """The ROM is not dumped, so ROM addresses executing says nothing about our output."""
    regions = dumper.plan_regions(_coverage((0x0000, 0x0100)))
    assert regions == [Region(RAM_BASE, ADDRESS_SPACE, DATA, "ram")]


def test_coverage_marks_instruction_starts_not_every_byte():
    """The bug that made real programs dump as data.

    Coverage records where an instruction *begins*, so executed code leaves a sparse
    trail: ``ld a,7 / out ($fe),a / ret`` marks 0x8000, 0x8002 and 0x8004 and leaves the
    operand bytes unmarked. Treating only consecutive marks as a run shreds that into
    one-byte fragments, every one of them below ``minimum_code_run`` -- so a genuinely
    executed routine comes out as data.

    It hid for a while because the early tests set coverage as a solid block of
    addresses, which no real program ever produces.
    """
    memory = FakeMemory(0x8000, bytes([0x3E, 0x07, 0xD3, 0xFE, 0xC9]))
    executed = bytearray(ADDRESS_SPACE)
    for start in (0x8000, 0x8002, 0x8004):      # instruction starts only
        executed[start] = 1

    without = dumper.plan_regions(executed, start=0x8000, end=0x8010)
    with_memory = dumper.plan_regions(executed, start=0x8000, end=0x8010, memory=memory)

    assert [r.kind for r in without] == [DATA]                    # the old, wrong answer
    assert with_memory[0] == Region(0x8000, 0x8005, CODE, "ram")  # the whole routine
    dumper.check_regions_tile(with_memory, 0x8000, 0x8010)


# --- the structural invariant ----------------------------------------------------

def test_a_gap_between_regions_is_rejected():
    """Bytes silently dropped from the rebuilt program."""
    with pytest.raises(ValueError, match="do not tile"):
        dumper.check_regions_tile(
            [Region(RAM_BASE, 0x5000, DATA), Region(0x6000, ADDRESS_SPACE, DATA)],
            RAM_BASE, ADDRESS_SPACE,
        )


def test_overlapping_regions_are_rejected():
    """Bytes silently duplicated."""
    with pytest.raises(ValueError, match="do not tile"):
        dumper.check_regions_tile(
            [Region(RAM_BASE, 0x6000, DATA), Region(0x5000, ADDRESS_SPACE, DATA)],
            RAM_BASE, ADDRESS_SPACE,
        )


def test_stopping_short_of_the_end_is_rejected():
    with pytest.raises(ValueError, match="stop at"):
        dumper.check_regions_tile([Region(RAM_BASE, 0x5000, DATA)], RAM_BASE, ADDRESS_SPACE)


# --- walking code ----------------------------------------------------------------

def test_an_instruction_never_runs_past_its_region():
    """The one overrun that breaks reassembly: the next region would start mid-instruction
    and every byte after it would shift. A straddling instruction becomes a byte instead."""
    memory = FakeMemory(0x8000, bytes([0x00, 0xC3]))   # nop, then jp nnnn (3 bytes)
    region = Region(0x8000, 0x8002, CODE)              # ...but only 2 bytes of room

    walked = list(dumper.walk_code(memory, region))

    assert walked[0][1] == "nop"
    assert walked[1][1] is None                        # emitted as a raw byte
    assert sum(length for _a, _t, length in walked) == region.size


def test_instruction_lengths_sum_to_the_region_size():
    memory = FakeMemory(0x8000, bytes([0x3E, 0x05, 0x00, 0xC9]))   # ld a,5 / nop / ret
    region = Region(0x8000, 0x8004, CODE)

    assert sum(length for _a, _t, length in dumper.walk_code(memory, region)) == region.size


# --- disassembly that would not survive a round trip -----------------------------

def test_a_redundant_index_prefix_is_kept_as_bytes():
    """Disassembly is not injective, and here that is fatal.

    ``DD DE nn`` is ``sbc a,n`` with a pointless IX prefix: the CPU ignores it, the
    disassembler rightly does not mention it, and an assembler then emits two bytes where
    there were three. Everything after shifts by one. This was found by the byte-identity
    test, and it surfaced thirty bytes *earlier* as a changed branch displacement, because
    the label it pointed at had moved.
    """
    memory = FakeMemory(0x8000, bytes([0xDD, 0xDE, 0xDF, 0xC9]))
    region = Region(0x8000, 0x8004, CODE)

    walked = list(dumper.walk_code(memory, region))

    assert walked[0][1] is None          # the stray prefix, emitted as a byte
    assert walked[1][1] == "sbc a,$DF"   # ...and the rest decodes normally from there
    assert sum(length for _a, _t, length in walked) == region.size


def test_a_real_index_instruction_is_still_disassembled():
    """The guard must not throw away genuine IX/IY code, which is most of what a prefix
    is actually for."""
    memory = FakeMemory(0x8000, bytes([0xDD, 0x7E, 0x05]))   # ld a,(ix+5)
    walked = list(dumper.walk_code(memory, Region(0x8000, 0x8003, CODE)))

    assert walked[0][1] is not None and "ix" in walked[0][1]


@pytest.mark.parametrize("opcode", [0x4C, 0x54, 0x7C, 0x55, 0x6D, 0x4E, 0x76, 0x7E])
def test_duplicate_ed_encodings_are_kept_as_bytes(opcode):
    """Seven byte patterns all mean ``neg``; print the name and the original is gone."""
    memory = FakeMemory(0x8000, bytes([0xED, opcode, 0xC9]))
    walked = list(dumper.walk_code(memory, Region(0x8000, 0x8003, CODE)))

    assert walked[0][1] is None


def test_the_canonical_ed_encoding_is_disassembled_normally():
    memory = FakeMemory(0x8000, bytes([0xED, 0x44, 0xC9]))   # the real `neg`
    walked = list(dumper.walk_code(memory, Region(0x8000, 0x8003, CODE)))

    assert walked[0][1] == "neg"


# --- labels ----------------------------------------------------------------------

def test_branch_targets_inside_code_become_labels():
    #  8000: jr $8004   8002: nop  8003: nop   8004: ret
    memory = FakeMemory(0x8000, bytes([0x18, 0x02, 0x00, 0x00, 0xC9]))
    regions = [Region(RAM_BASE, 0x8000, DATA), Region(0x8000, 0x8005, CODE),
               Region(0x8005, ADDRESS_SPACE, DATA)]

    labels = dumper.collect_labels(memory, regions)

    assert labels[0x8004] == "L8004"
    assert labels[0x8000] == "ram_8000"     # region starts are always named


def test_a_target_that_is_not_an_instruction_boundary_gets_no_label():
    """A label can only be *used* where it will also be *defined*. Mid-instruction, or
    inside a data blob, there is nowhere to put one -- so the address stays as hex, which
    is less readable and still assembles to the same bytes."""
    memory = FakeMemory(0x8000, bytes([0xC3, 0x00, 0x50, 0xC9]))   # jp $5000 (in data)
    regions = [Region(RAM_BASE, 0x8000, DATA), Region(0x8000, 0x8004, CODE),
               Region(0x8004, ADDRESS_SPACE, DATA)]

    labels = dumper.collect_labels(memory, regions)

    assert 0x5000 not in labels


def test_a_branch_destination_is_rendered_as_its_label():
    memory = FakeMemory(0x8000, bytes([0x18, 0x02, 0x00, 0x00, 0xC9]))
    regions = [Region(0x8000, 0x8005, CODE)]
    labels = dumper.collect_labels(memory, regions)

    text = "\n".join(dumper.render_code(memory, regions[0], labels))

    assert "jr L8004" in text
    assert "L8004:" in text


def test_rom_calls_are_named_but_not_defined():
    """The ROM is not dumped, so its routines are emitted as equates -- which turns
    `call $0556` into something you can read without changing a byte."""
    memory = FakeMemory(0x8000, bytes([0xCD, 0x56, 0x05, 0xC9]))   # call $0556 / ret
    regions = [Region(0x8000, 0x8004, CODE)]

    used = dumper.rom_symbols_used(memory, regions)

    assert 0x0556 in used
    assert used[0x0556].replace("_", "").isalnum()      # a legal sjasmplus label


def test_rom_label_names_are_made_assembler_safe():
    assert dumper._safe_label("SA/LD-RET") == "SA_LD_RET"


# --- data ------------------------------------------------------------------------

def test_data_is_emitted_with_addresses_so_you_can_find_your_place():
    memory = FakeMemory(0x8000, bytes(range(16)))
    lines = dumper.render_data(memory, Region(0x8000, 0x8010, DATA))

    assert lines[0] == "ram_8000:"
    assert lines[1].startswith("    db $00,$01")
    assert lines[1].rstrip().endswith("; $8000")
    assert len(lines) == 1 + 16 // dumper.DB_BYTES_PER_LINE
