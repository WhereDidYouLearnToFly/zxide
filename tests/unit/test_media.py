"""Tests for zxemu_ui.media -- which loader a file needs, and what to say about it.

No Qt here: that is the point of the module existing. Everything the window used to do
inline can now be asked a question instead of driven through a dialog.
"""

from __future__ import annotations

import importlib.resources as res

import pytest

from zxemu_core.machine import Machine, Machine128
from zxemu_ui import media


def _rom() -> bytes:
    return (res.files("zxemu_core") / "roms" / "48.rom").read_bytes()


def _roms_128() -> tuple[bytes, bytes]:
    folder = res.files("zxemu_core") / "roms"
    return (folder / "128-0.rom").read_bytes(), (folder / "128-1.rom").read_bytes()


def _tap_block(flag: int, payload: bytes) -> bytes:
    body = bytes([flag]) + payload
    checksum = 0
    for byte in body:
        checksum ^= byte
    block = body + bytes([checksum])
    return bytes([len(block) & 0xFF, len(block) >> 8]) + block


# --- which loader ------------------------------------------------------------

@pytest.mark.parametrize("name, kind", [
    ("game.sna", media.SNAPSHOT),
    ("game.z80", media.SNAPSHOT),
    ("GAME.Z80", media.SNAPSHOT),   # suffix matching is case-insensitive
    ("game.tap", media.TAPE),
    ("game.tzx", media.TAPE),
    ("game.szx", None),             # a real format we don't read yet
    ("notes.txt", None),
])
def test_kind_of_classifies_by_suffix(name, kind):
    assert media.kind_of(name) == kind


def test_the_format_table_covers_every_suffix_the_loaders_handle():
    """FORMATS is the single source of truth: the Load menu, the file dialogs' filters
    and the suffix sets all come from it, so a format added here needs nothing else."""
    assert [f.suffix for f in media.FORMATS] == [".tap", ".tzx", ".sna", ".z80"]
    assert media.TAPE_SUFFIXES == {".tap", ".tzx"}
    assert media.SNAPSHOT_SUFFIXES == {".sna", ".z80"}


def test_each_format_names_itself_for_the_menu_and_the_dialog():
    tap = media.format_of("game.TAP")
    assert tap.menu_label == "Load TAP…"
    assert tap.file_filter == "TAP tape image (*.tap)"
    assert media.format_of("nope.szx") is None


# --- snapshots ---------------------------------------------------------------

def test_load_snapshot_picks_the_z80_loader_for_z80(tmp_path):
    machine = Machine(_rom())
    header = bytearray(30)
    header[0], header[1] = 0x12, 0x34          # A, F
    header[6], header[7] = 0x00, 0x90          # PC = 0x9000 -> a v1 file
    path = tmp_path / "game.z80"
    path.write_bytes(bytes(header) + bytes(3 * 0x4000))

    media.load_snapshot(machine, path)

    assert machine.cpu.regs.pc == 0x9000 and machine.cpu.regs.a == 0x12


def test_load_snapshot_picks_the_sna_loader_for_sna(tmp_path):
    machine = Machine(_rom())
    data = bytearray(49179)
    data[23], data[24] = 0x00, 0x80            # SP = 0x8000
    data[27 + (0x8000 - 0x4000)] = 0x34        # the word at SP: PC = 0x1234
    data[27 + (0x8000 - 0x4000) + 1] = 0x12
    path = tmp_path / "game.sna"
    path.write_bytes(bytes(data))

    media.load_snapshot(machine, path)

    assert machine.cpu.regs.pc == 0x1234  # .sna takes PC off the stack, as a RETN does


def test_load_snapshot_lets_the_loader_s_error_through(tmp_path):
    """The window turns these into one "could not load" line -- clicking a 128K snapshot
    while running a 48K machine is a normal mistake, not an internal error."""
    machine = Machine128(*_roms_128())
    path = tmp_path / "48k.z80"
    header = bytearray(30)
    header[6], header[7] = 0x00, 0x80
    path.write_bytes(bytes(header) + bytes(3 * 0x4000))

    with pytest.raises(ValueError):
        media.load_snapshot(machine, path)


# --- tapes -------------------------------------------------------------------

def test_read_tape_parses_a_tap_with_no_notes(tmp_path):
    path = tmp_path / "game.tap"
    path.write_bytes(_tap_block(0xFF, bytes([1, 2, 3])))

    blocks, notes = media.read_tape(path)

    assert len(blocks) == 1 and notes == []  # a .tap is only blocks


def test_read_tape_parses_a_tzx_and_returns_its_notes(tmp_path):
    from zxemu_core.storage.tzx import TZX_SIGNATURE

    block = bytes([0xFF, 1, 2]) + bytes([0xFF ^ 1 ^ 2])
    standard = bytes([0x10, 0, 0, len(block), 0]) + block
    text = bytes([0x30, 5]) + b"hello"
    path = tmp_path / "game.tzx"
    path.write_bytes(TZX_SIGNATURE + b"\x01\x14" + text + standard)

    blocks, notes = media.read_tape(path)

    assert len(blocks) == 1
    assert any("hello" in note for note in notes)


def test_tape_summary_lists_the_blocks_and_says_how_to_start_it(tmp_path):
    path = tmp_path / "game.tap"
    path.write_bytes(_tap_block(0xFF, bytes([1, 2])) + _tap_block(0xFF, bytes([3])))
    blocks, notes = media.read_tape(path)

    lines_48 = media.tape_summary("game.tap", blocks, notes, "48k")
    lines_128 = media.tape_summary("game.tap", blocks, notes, "128k")

    assert lines_48[0] == "Inserted game.tap — 2 loadable block(s):"
    assert len(lines_48) == 4  # header + two blocks + the how-to-start line
    assert 'LOAD ""' in lines_48[-1] and "J key" in lines_48[-1]
    # The 128K boots to its own menu, so there is no LOAD prompt until you leave it.
    assert "128 BASIC" in lines_128[-1]


def test_tape_summary_includes_the_parser_s_notes(tmp_path):
    path = tmp_path / "game.tap"
    path.write_bytes(_tap_block(0xFF, b"\x01"))
    blocks, _ = media.read_tape(path)

    lines = media.tape_summary("game.tzx", blocks, ["Skipped $23 (jump)"], "48k")

    assert any("Skipped $23" in line for line in lines)
