"""Unit tests for the Pentagon 128 machine model.

A Pentagon is a 128K in almost every respect, which is exactly the danger: the ways it
*isn't* one are easy to leave unimplemented and impossible to notice by looking at the
screen. A wrong frame length or stray contention shows up only as demos running at
subtly the wrong speed, months later. So each difference gets a test that names it.
"""

import importlib.resources as res

from zxemu_core.machine import Machine128, MachinePentagon
from zxemu_core.memlayout import PAGED_MODELS, bank_ids_for_model
from zxemu_core.ula import FRAME_TSTATES_128K, FRAME_TSTATES_PENTAGON
from zxemu_ui.machine_factory import build_machine, machine_model


def _rom(name: str) -> bytes:
    return (res.files("zxemu_core") / "roms" / name).read_bytes()


def _pentagon() -> MachinePentagon:
    return MachinePentagon(_rom("128p-0.rom"), _rom("128p-1.rom"))


# --- the three real differences ------------------------------------------------

def test_the_frame_is_longer_than_a_sinclair_128s():
    """224 lines of 320 T-states. Soviet demos are timed against this cadence, so
    running them on a 70908-T frame makes them wrong in a way nothing reports."""
    assert FRAME_TSTATES_PENTAGON == 71680 == 224 * 320
    assert _pentagon().frame_tstates == FRAME_TSTATES_PENTAGON
    assert Machine128(_rom("128-0.rom"), _rom("128-1.rom")).frame_tstates == FRAME_TSTATES_128K


def test_no_ram_bank_contends_with_the_ula():
    """The clone rebuilt the ULA in discrete logic and did not reproduce contention.
    This is the hardware being simpler, not the emulator cutting a corner."""
    pentagon = _pentagon()
    assert [n for n, bank in enumerate(pentagon.ram_banks) if bank.contended] == []

    sinclair = Machine128(_rom("128-0.rom"), _rom("128-1.rom"))
    assert [n for n, bank in enumerate(sinclair.ram_banks) if bank.contended] == [1, 3, 5, 7]


def test_the_rom_is_the_tr_dos_aware_one():
    """The 65-byte patch that makes 128p-0 a Pentagon ROM: the "Tape Tester" menu entry
    becomes "TR-DOS". Spectrum ROM strings mark their last character with bit 7, hence
    the odd-looking terminator."""
    rom0 = bytes(_pentagon().rom_banks[0].data)
    assert b"TR-DO" + bytes([ord("S") | 0x80]) in rom0
    assert b"Tape Tester" not in rom0
    # ...and the code added alongside it enters TR-DOS the documented way.
    assert b"15616" in rom0  # RANDOMIZE USR 15616, and 15616 == 0x3D00


def test_rom1_is_the_stock_48_basic():
    """Pentagon patched only ROM0. If this ever diverges, the ROM set is not what we think."""
    assert bytes(_pentagon().rom_banks[1].data) == _rom("128-1.rom")


# --- everything else must still be a 128K ---------------------------------------

def test_paging_and_the_bank_pool_are_unchanged():
    pentagon = _pentagon()
    assert len(pentagon.ram_banks) == 8 and len(pentagon.rom_banks) == 2
    pentagon.set_paging(0x07)               # RAM7 into slot 3
    assert pentagon.memory.slots[3] is pentagon.ram_banks[7]
    pentagon.set_paging(0x08)               # shadow screen
    assert pentagon.display_memory() is pentagon.ram_banks[7].data


def test_the_address_space_counts_as_a_paged_model():
    """Asset placement, the memory map and the build's ORG/PAGE lines all key off this;
    treating Pentagon as a 48K would put assets at addresses that don't exist."""
    assert "pentagon" in PAGED_MODELS
    assert bank_ids_for_model("pentagon") == bank_ids_for_model("128k")


# --- the factory ----------------------------------------------------------------

def test_the_factory_round_trips_the_model_string():
    machine = build_machine("pentagon")
    assert isinstance(machine, MachinePentagon)
    assert machine_model(machine) == "pentagon"


def test_a_pentagon_is_not_reported_as_a_128k():
    """It subclasses Machine128, so the obvious isinstance order silently mislabels it --
    and the model string is what gets written into the project manifest."""
    assert machine_model(build_machine("128k")) == "128k"
    assert machine_model(build_machine("48k")) == "48k"


def test_an_unknown_model_falls_back_rather_than_raising():
    """The model comes out of a hand-editable manifest; a typo should open the project on
    a safe machine, not refuse to open it."""
    assert machine_model(build_machine("pentagon-1024")) == "48k"


# --- it actually boots -----------------------------------------------------------

def test_reset_takes_the_disk_interface_with_it():
    """A reset from inside TR-DOS must come back to the Pentagon menu, not to TR-DOS.

    The reset line reaches the Beta 128 too. Miss that, and ``Machine128.reset`` re-pages
    slot 0 through ``rom_for_slot0()`` -- which answers "TR-DOS" while the interface is
    paged -- so the machine restarts by executing the disk operating system from address
    0. The screen fills with garbage and the Reset button looks broken.
    """
    pentagon = build_machine("pentagon")
    pentagon.set_paging(0x10)          # 48 BASIC selected, as BASIC runs under
    pentagon.beta.m1(0x3D00)           # enter TR-DOS
    assert pentagon.beta.paged

    pentagon.reset()

    assert not pentagon.beta.paged
    assert pentagon.paging_state().slot_labels[0] == "ROM0"
    assert pentagon.memory.read_byte(0) == pentagon.rom_banks[0].data[0]


def test_reset_also_stops_the_drive():
    """Whatever the controller was in the middle of is abandoned; leaving a transfer
    half-served would have the next command answer with the last disk's bytes."""
    pentagon = build_machine("pentagon")
    controller = pentagon.beta.controller
    controller.data = 42
    controller.track = 30
    controller.intrq = True

    pentagon.reset()

    assert controller.track == 0 and not controller.intrq


def test_it_boots_its_menu():
    """Cheap smoke test that the ROM runs at all: after a couple of seconds the menu has
    been drawn into the screen bank. What the menu *says* is checked in the integration
    test, which renders it."""
    pentagon = _pentagon()
    for _ in range(300):
        pentagon.run_frame()
    screen = pentagon.display_memory()[:6144]
    assert sum(1 for byte in screen if byte) > 100
