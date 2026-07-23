"""Tests for memory search, cross-references and coverage (zxemu_core.analysis)."""

from __future__ import annotations

from zxemu_core import analysis
from zxemu_core.machine import Machine


def _machine(program: dict | None = None) -> Machine:
    rom = bytearray(0x4000)
    for address, data in (program or {}).items():
        rom[address:address + len(data)] = data
    return Machine(bytes(rom))


# --- search -------------------------------------------------------------------

def test_search_finds_a_byte_sequence():
    m = _machine()
    for i, b in enumerate((0x21, 0x00, 0x40)):
        m.memory.write_byte(0x9000 + i, b)
    assert analysis.search_bytes(m.memory, bytes([0x21, 0x00, 0x40])) == [0x9000]


def test_search_finds_every_occurrence():
    m = _machine()
    m.memory.write_byte(0x9000, 0xAA)
    m.memory.write_byte(0x9100, 0xAA)
    assert analysis.search_bytes(m.memory, bytes([0xAA]), start=0x8000) == [0x9000, 0x9100]


def test_search_respects_the_range():
    m = _machine()
    m.memory.write_byte(0x9000, 0xAA)
    assert analysis.search_bytes(m.memory, bytes([0xAA]), start=0x9001) == []


def test_empty_pattern_finds_nothing():
    assert analysis.search_bytes(_machine().memory, b"") == []


def test_text_search():
    m = _machine()
    for i, b in enumerate(b"HELLO"):
        m.memory.write_byte(0x9000 + i, b)
    assert analysis.search_text(m.memory, "HELLO", start=0x8000) == [0x9000]


# --- cross-references ---------------------------------------------------------

def test_finds_a_call_to_the_target():
    m = _machine({0x0100: bytes([0xCD, 0x00, 0x90])})  # CALL $9000
    references = analysis.cross_references(m.memory, 0x9000, end=0x4000)
    assert analysis.Reference(0x0100, "call") in references


def test_distinguishes_call_jump_read_and_write():
    m = _machine({
        0x0100: bytes([0xCD, 0x00, 0x90]),  # CALL $9000
        0x0200: bytes([0xC3, 0x00, 0x90]),  # JP   $9000
        0x0300: bytes([0x3A, 0x00, 0x90]),  # LD A,($9000)
        0x0400: bytes([0x32, 0x00, 0x90]),  # LD ($9000),A
    })
    kinds = {r.address: r.kind for r in analysis.cross_references(m.memory, 0x9000, end=0x4000)}
    assert kinds[0x0100] == "call"
    assert kinds[0x0200] == "jump"
    assert kinds[0x0300] == "read"
    assert kinds[0x0400] == "write"


def test_finds_an_immediate_pointer_load():
    """`ld hl,$4000` is how Z80 code usually refers to an address -- xrefs must see it."""
    m = _machine({0x0100: bytes([0x21, 0x00, 0x40])})  # LD HL,$4000
    references = analysis.cross_references(m.memory, 0x4000, end=0x4000)
    assert analysis.Reference(0x0100, "load") in references


def test_immediate_loads_of_every_pair_are_found():
    m = _machine({
        0x0100: bytes([0x01, 0x00, 0x40]),  # LD BC,$4000
        0x0200: bytes([0x11, 0x00, 0x40]),  # LD DE,$4000
        0x0300: bytes([0x31, 0x00, 0x40]),  # LD SP,$4000
    })
    addresses = {r.address for r in analysis.cross_references(m.memory, 0x4000, end=0x4000)}
    assert {0x0100, 0x0200, 0x0300} <= addresses


def test_ignores_a_matching_operand_under_an_unrelated_opcode():
    m = _machine({0x0100: bytes([0x00, 0x00, 0x90])})  # NOP, then bytes that look like an operand
    assert analysis.cross_references(m.memory, 0x9000, end=0x4000) == []


# --- coverage -----------------------------------------------------------------

def test_coverage_records_and_counts():
    coverage = analysis.CoverageMap()
    coverage.mark(0x8000)
    coverage.mark(0x8001)
    coverage.mark(0x8000)  # again: still one address
    assert coverage.count() == 2


def test_coverage_collapses_into_runs():
    coverage = analysis.CoverageMap()
    for address in range(0x8000, 0x8010):
        coverage.mark(address)
    for address in range(0x9000, 0x9004):
        coverage.mark(address)
    assert coverage.ranges() == [(0x8000, 0x8010), (0x9000, 0x9004)]


def test_coverage_clear_forgets_everything():
    coverage = analysis.CoverageMap()
    coverage.mark(0x8000)
    coverage.clear()
    assert coverage.count() == 0
