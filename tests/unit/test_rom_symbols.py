"""Tests for 48K ROM routine names (zxemu_core.debug.rom_symbols)."""

from __future__ import annotations

import importlib.resources as res

from zxemu_core.debug import rom_symbols
from zxemu_core.machine import Machine, Machine128


def _roms():
    root = res.files("zxemu_core") / "roms"
    return (root / "48.rom").read_bytes(), (root / "128-0.rom").read_bytes(), (root / "128-1.rom").read_bytes()


def test_known_restart_is_named():
    assert rom_symbols.name_for(0x0010) == "PRINT-A"
    assert rom_symbols.name_for(0x0038) == "MASK-INT"


def test_unknown_address_has_no_name():
    assert rom_symbols.name_for(0x1234) is None


def test_ld_bytes_matches_the_address_the_tape_trap_uses():
    """The tape fast-loader and the symbol table must agree on where LD-BYTES is."""
    from zxemu_core.storage import tape

    assert rom_symbols.name_for(tape.LD_BYTES_ENTRY) == "LD-BYTES"


def test_annotate_names_a_call_target():
    assert rom_symbols.annotate("call $15E6") == "call $15E6  ; INPUT-AD"


def test_annotate_leaves_unknown_targets_alone():
    assert rom_symbols.annotate("call $8000") == "call $8000"


def test_annotate_ignores_addresses_above_the_rom():
    """A RAM address that coincides with a ROM symbol's low bits must not be labelled."""
    assert rom_symbols.annotate("ld hl,($5C5D)") == "ld hl,($5C5D)"


def test_annotate_can_be_disabled():
    assert rom_symbols.annotate("call $15E6", enabled=False) == "call $15E6"


def test_enclosing_names_the_routine_you_are_inside():
    """While stepping, PC is usually mid-routine rather than at an entry point."""
    assert rom_symbols.enclosing(0x028E) == ("KEY-SCAN", 0)
    assert rom_symbols.enclosing(0x0292) == ("KEY-SCAN", 4)


def test_enclosing_gives_up_rather_than_guessing_wildly():
    """The table is sparse; past the limit, the nearest name would be invention."""
    assert rom_symbols.enclosing(0x3000) is None  # far from any known entry point


def test_enclosing_ignores_addresses_outside_the_rom():
    assert rom_symbols.enclosing(0x8000) is None


def test_48k_machine_always_has_valid_rom_symbols():
    rom48, _, _ = _roms()
    assert Machine(rom48).rom_symbols_valid() is True


def test_128k_symbols_are_valid_only_while_48_basic_is_paged():
    """With ROM 0 (the 128 editor) paged, these addresses hold different code entirely."""
    _, rom0, rom1 = _roms()
    m = Machine128(rom0, rom1)

    m.set_paging(0x00, force=True)          # ROM 0 -- the 128 editor
    assert m.rom_symbols_valid() is False

    m.set_paging(0x10, force=True)          # ROM 1 -- 48 BASIC
    assert m.rom_symbols_valid() is True
