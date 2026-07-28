"""Reading a compiled AY module, which is a headerless blob that has to be inferred.

There is no magic number and no load address in these files, so everything here is
deduction -- and the cost of deducing wrong is not an error but an emulated Z80 executing
whatever the bytes happen to mean. These tests are mostly about the deduction *failing
loudly* rather than about the happy path.

The fixtures are built by hand rather than checked in as binaries: a real compiled module
is someone's copyrighted music, and the three facts the reader depends on (opening
``LD HL,nnnn``, a tracker signature, and the arithmetic between them) are expressible in
a dozen bytes.
"""

import pytest

from zxemu_core.sound.ay_program import NotACompiledModule, looks_compiled, read_compiled


def _module(org: int = 0xC000, data_offset: int = 0x40, size: int = 0x80) -> bytes:
    """A minimal blob shaped like a compiled module: LD HL,<data> then a signature there."""
    blob = bytearray(size)
    pointer = org + data_offset
    blob[0] = 0x21                       # LD HL,nnnn
    blob[1] = pointer & 0xFF
    blob[2] = pointer >> 8
    signature = b"ProTracker 3.5 compilation of Test Tune"
    blob[data_offset:data_offset + len(signature)] = signature
    return bytes(blob)


def test_the_load_address_is_derived_from_the_pointer_and_the_signature():
    """ORG = (address in LD HL,nnnn) - (offset of the signature). The two facts check each
    other, which is what makes this deduction rather than a guess."""
    program = read_compiled(_module(org=0xC000, data_offset=0x40))
    assert program.extras["org"] == 0xC000
    assert program.blocks[0][0] == 0xC000


def test_a_module_that_loads_somewhere_else_is_read_correctly_too():
    """The 0xC000 convention is overwhelmingly common and still only a convention --
    assuming it would mis-load everything built for anywhere else."""
    program = read_compiled(_module(org=0x8000, data_offset=0x60))
    assert program.extras["org"] == 0x8000


def test_entry_points_follow_the_players_own_documented_layout():
    """init at +0, play at +5, mute at +8 -- the layout Bulba's player states in its source
    and every player copying it reproduces (verified again in ZiFi's pt2.asm prologue)."""
    program = read_compiled(_module(org=0xC000))
    assert (program.init, program.play, program.mute) == (0xC000, 0xC005, 0xC008)


def test_the_title_comes_out_of_the_module_data():
    assert "Test Tune" in read_compiled(_module()).title


def test_a_file_that_does_not_start_with_ld_hl_is_refused():
    """No pointer means no way to locate the data, so no way to derive the load address."""
    blob = bytearray(_module())
    blob[0] = 0xC9  # RET
    with pytest.raises(NotACompiledModule):
        read_compiled(bytes(blob))


def test_a_file_with_no_tracker_signature_is_refused():
    """Half the deduction missing. Better to refuse than to assume 0xC000 -- which is right
    often enough to be dangerous, and wrong silently."""
    blob = bytearray(_module())
    del blob[0x40:0x60]
    with pytest.raises(NotACompiledModule):
        read_compiled(bytes(blob))


def test_an_implied_address_outside_ram_is_refused():
    """The arithmetic landing under 0x4000 means the two facts disagree, so at least one of
    them is not what it looked like."""
    with pytest.raises(NotACompiledModule):
        read_compiled(_module(org=0x0100))


def test_a_truncated_file_is_refused_rather_than_indexed_into():
    with pytest.raises(NotACompiledModule):
        read_compiled(b"\x21\x00\xC0")


def test_looks_compiled_answers_without_raising():
    """For the UI, which asks "can I offer to play this?" about every file it sees."""
    assert looks_compiled(_module())
    assert not looks_compiled(b"just some text in a file")
