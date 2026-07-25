"""TR-DOS itself reading a disk we built, on a Pentagon we built.

The disk tests in ``tests/unit/test_disk.py`` check that our own code agrees with our own
code. That is worth having and proves nothing about whether a real machine can use the
result -- the format is only correct if the operating system that invented it says so.

So this asks TR-DOS. A Pentagon boots, the menu's TR-DOS entry is chosen with the arrow
keys, ``CAT`` is typed, and the screen is read back. Everything in between is TR-DOS's own
5.03 code driving the WD1793 through the Beta 128's ports: Restore, Seek, Read Address,
Read Sector. If the catalogue layout, the sector interleave, the geometry, the status bits
or the INTRQ/DRQ handshake were wrong, the answer would be "No disk" -- as it was, once.

The screen is read by matching character cells against the ROM's own font, which is the
only text there is: a Spectrum screen is a bitmap and nothing records what was printed.
"""

from __future__ import annotations

import importlib.resources as res

import pytest

from zxemu_core.storage.disk.scl import parse_scl
from zxemu_core.storage.disk.trd import (
    INFO_OFFSET,
    SECTOR_SIZE,
    TRACK_SIZE,
    TRDOS_ID,
    TrdImage,
)
from zxemu_ui.machine_factory import build_machine

# Where the 48K ROM keeps its 8x8 font, minus the 32 characters it has no glyphs for.
FONT_BASE = 0x3D00 - 32 * 8
SCREEN_BASE = 0x4000


def _rom48() -> bytes:
    return (res.files("zxemu_core") / "roms" / "48.rom").read_bytes()


# --- driving the machine --------------------------------------------------------

def _tap(machine, *keys, hold=6, gap=6):
    for key in keys:
        machine.keyboard.press(key)
    for _ in range(hold):
        machine.run_frame()
    machine.keyboard.release_all()
    for _ in range(gap):
        machine.run_frame()


def _enter_trdos(machine):
    """Boot, then pick TR-DOS: the fifth entry, so four presses of the down arrow.

    Chosen over poking PC to 0x3D00 deliberately -- going through the menu exercises the
    Pentagon ROM's own entry code and the Beta's address-bus paging together, which is
    the pair most likely to be subtly wrong.
    """
    for _ in range(250):
        machine.run_frame()
    for _ in range(4):
        _tap(machine, "CAPS SHIFT", "6")     # down arrow
    _tap(machine, "ENTER")
    for _ in range(200):
        machine.run_frame()


def _type_cat(machine):
    """CAT is an extended-mode keyword: CAPS+SYMBOL SHIFT, then SYMBOL SHIFT + 9."""
    _tap(machine, "CAPS SHIFT", "SYM SHIFT")
    _tap(machine, "SYM SHIFT", "9")
    _tap(machine, "ENTER")
    for _ in range(400):
        machine.run_frame()


# --- reading the screen back ----------------------------------------------------

def _screen_text(machine) -> list[str]:
    """Decode the screen to text by matching each cell against the ROM font."""
    font = _rom48()
    glyphs = {}
    for code in range(32, 128):
        start = FONT_BASE + code * 8
        glyphs[bytes(font[start:start + 8])] = chr(code)

    memory = machine.memory
    lines = []
    for row in range(24):
        line = ""
        for column in range(32):
            cell = bytes(
                memory.read_byte(_cell_address(row, column, scan))
                for scan in range(8)
            )
            line += glyphs.get(cell, " " if not any(cell) else "?")
        lines.append(line.rstrip())
    return lines


def _cell_address(row: int, column: int, scan: int) -> int:
    """The Spectrum's famously non-linear screen layout, one scanline of one cell."""
    third, within = divmod(row, 8)
    return SCREEN_BASE + (third << 11) + (scan << 8) + (within << 5) + column


# --- fixtures -------------------------------------------------------------------

def _disk_with_files() -> TrdImage:
    """An SCL built here, so the expected catalogue is known exactly rather than read
    from a file that might not be on the machine running the tests."""
    entries, payload = b"", b""
    for name, sectors, fill in (("HELLO", 3, 0x11), ("WORLD", 2, 0x22)):
        entries += (name.ljust(8).encode() + b"C" + b"\x00\x80"
                    + b"\x00\x03" + bytes([sectors]))
        payload += bytes([fill]) * (sectors * SECTOR_SIZE)
    scl = b"SINCLAIR" + bytes([2]) + entries + payload + b"\x00\x00\x00\x00"
    return parse_scl(scl, "TESTDISK.scl")


@pytest.fixture(scope="module")
def pentagon_with_disk():
    machine = build_machine("pentagon")
    machine.beta_drives[0] = _disk_with_files()
    _enter_trdos(machine)
    _type_cat(machine)
    return machine


# --- the tests ------------------------------------------------------------------

def test_the_pentagon_reaches_the_tr_dos_prompt():
    machine = build_machine("pentagon")
    _enter_trdos(machine)
    text = "\n".join(_screen_text(machine))
    assert "TR-DOS" in text
    assert "5.03" in text


def test_tr_dos_reads_the_catalogue_of_a_disk_we_built(pentagon_with_disk):
    """The end-to-end proof. Every number here came out of TR-DOS reading sectors through
    our controller -- not out of our own parser."""
    text = "\n".join(_screen_text(pentagon_with_disk))
    assert "TESTDISK" in text          # the label SCL conversion invented from the filename
    assert "2 File" in text
    assert "HELLO" in text and "WORLD" in text


def test_the_beta_rom_pages_in_and_out_on_the_address_bus():
    """The mechanism behind RANDOMIZE USR 15616, and the reason the CPU has an m1_hook."""
    machine = build_machine("pentagon")
    beta = machine.beta
    machine.set_paging(0x10)           # select ROM1 (48 BASIC), as BASIC runs under

    beta.m1(0x3D00)
    assert beta.paged
    assert machine.memory.read_byte(0) == machine.trdos_rom.data[0]

    beta.m1(0x8000)                    # a fetch from RAM takes it back out
    assert not beta.paged
    assert machine.memory.read_byte(0) == machine.rom_banks[1].data[0]


def test_the_beta_keeps_out_of_the_way_of_the_128_menu_rom():
    """With ROM0 paged, 0x3Dxx is ordinary menu code that must be allowed to run --
    paging TR-DOS over it would break the machine before you ever reached a disk."""
    machine = build_machine("pentagon")
    machine.set_paging(0x00)           # ROM0: the 128 editor
    machine.beta.m1(0x3D00)
    assert not machine.beta.paged


def test_the_disk_ports_are_dead_while_tr_dos_is_paged_out():
    """Port 0xFF is how every 128K game samples the floating bus. If the controller
    answered those reads it would be taking status polls from programs that have never
    heard of it."""
    machine = build_machine("pentagon")
    assert not machine.beta.paged
    assert not machine.beta.handles(0xFF)
    machine.set_paging(0x10)
    machine.beta.m1(0x3D00)
    assert machine.beta.handles(0xFF)


def test_run_boots_the_disk_and_reset_gets_back_out_of_it():
    """Typing RUN in TR-DOS loads and runs the disk's ``boot`` file, and Reset then
    returns to the Pentagon menu. Both halves were broken and are worth pinning together,
    because the second is what you reach for when the first misbehaves.

    RUN used to wedge the machine solid: TR-DOS writes 0xFF to the command register while
    probing, that decodes to Write Track, and the controller parked with DRQ raised
    waiting for a track's worth of bytes that never arrived. Reset could not recover it
    either -- resetting from inside TR-DOS re-paged *TR-DOS* into slot 0 and restarted the
    CPU inside the disk operating system.
    """
    machine = build_machine("pentagon")
    machine.beta_drives[0] = _disk_with_files()
    _enter_trdos(machine)

    _tap(machine, "R")                 # RUN is a plain keyword-mode key
    _tap(machine, "ENTER")
    for _ in range(600):
        machine.run_frame()

    # Whatever the boot file did, the machine must still be *alive*: the controller is
    # not parked mid-command and TR-DOS has moved on from the command it issued.
    assert machine.beta.controller._state != "formatting"

    machine.reset()
    for _ in range(300):
        machine.run_frame()

    assert not machine.beta.paged
    assert machine.memory.read_byte(0) == machine.rom_banks[0].data[0]
    assert "TR-DOS" in "\n".join(_screen_text(machine))   # ...back at the Pentagon menu


def test_a_probing_write_track_does_not_erase_the_disk():
    """End-to-end guard for the worst bug in this subsystem so far.

    A disk loader selects a file, TR-DOS probes with 0xFF (= Write Track) while sitting
    on track 0, and an implementation that honours that literally erases the catalogue
    and the information block. The symptom is "Disk Error" on a disk that was readable
    seconds earlier -- and the disk stays broken for the rest of the session.
    """
    machine = build_machine("pentagon")
    image = _disk_with_files()
    machine.beta_drives[0] = image
    track0 = bytes(image.data[:TRACK_SIZE])

    _enter_trdos(machine)
    controller = machine.beta.controller
    controller.select(0, 0)
    controller.write_command(0x00)      # Restore: park on track 0, where a probe lands
    controller.write_command(0xFF)      # ...and probe

    assert bytes(image.data[:TRACK_SIZE]) == track0
    assert [f.name for f in image.catalogue()] == ["HELLO", "WORLD"]

    _type_cat(machine)
    assert "2 File" in "\n".join(_screen_text(machine))


def test_a_write_through_the_controller_is_read_back_by_tr_dos():
    """Writes reach the image *and* TR-DOS sees them -- the two halves of the write path,
    checked together by changing the disk label and asking TR-DOS for the title."""
    machine = build_machine("pentagon")
    image = TrdImage(bytes(80 * 2 * TRACK_SIZE))
    block = bytearray(0x20)
    block[0x03], block[0x07] = 0x16, TRDOS_ID
    block[0x15:0x1D] = b"BEFORE  "
    image.data[INFO_OFFSET:INFO_OFFSET + 0x20] = block
    machine.beta_drives[0] = image

    controller = machine.beta.controller
    controller.select(0, 0)
    controller.write_command(0x00)                    # Restore to track 0
    controller.sector = 9                             # the information sector
    sector = bytearray(image.read_sector(0, 0, 9))
    sector[0xE0 + 0x15:0xE0 + 0x1D] = b"AFTER   "
    controller.write_command(0xA0)                    # Write Sector
    for byte in sector:
        controller.write_data(byte)

    assert image.info().label == "AFTER"
    assert image.dirty

    _enter_trdos(machine)
    _type_cat(machine)
    assert "AFTER" in "\n".join(_screen_text(machine))
