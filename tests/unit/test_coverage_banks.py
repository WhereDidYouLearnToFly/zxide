"""Coverage remembers *which bank* was mapped, because nothing else can.

Below 0xC000 an address identifies its bank on its own -- slot 1 is always RAM5, slot 2
always RAM2. Above it, eight banks take turns, and "0xC123 executed" says nothing about
which one was there.

That is not recoverable afterwards, and the temptation to try is the reason this file
opens with the point: two banks may hold identical bytes, a bank may be modified after its
code ran, and a program can swap banks at that address hundreds of times a second. The
information has to be written down as it happens, which the machine is well placed to do
because ``set_paging`` is the single point the mapping moves.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from zxemu_core.debug.analysis import PAGED_BASE, CoverageMap  # noqa: E402
from zxemu_ui.controller import EmulatorController  # noqa: E402
from zxemu_ui.machine_factory import build_machine  # noqa: E402


# --- the map itself --------------------------------------------------------------

def test_marks_above_the_paged_base_land_in_the_selected_bank():
    coverage = CoverageMap()
    coverage.select_bank(3)

    coverage.mark(0xC123)

    assert coverage.executed_in_bank(3)[0xC123 - PAGED_BASE] == 1
    assert coverage.executed_in_bank(4) is None      # never selected, never allocated


def test_switching_banks_splits_coverage_between_them():
    """The case the whole feature exists for: the same address, two different banks."""
    coverage = CoverageMap()
    coverage.select_bank(3)
    coverage.mark(0xC000)
    coverage.select_bank(6)
    coverage.mark(0xC010)

    assert coverage.executed_in_bank(3)[0x0000] == 1
    assert coverage.executed_in_bank(3)[0x0010] == 0     # bank 6 ran that one
    assert coverage.executed_in_bank(6)[0x0010] == 1
    assert coverage.executed_in_bank(6)[0x0000] == 0


def test_addresses_below_the_paged_base_need_no_bank():
    """Slots 1 and 2 never move, so the flat map already identifies them."""
    coverage = CoverageMap()
    coverage.select_bank(3)

    coverage.mark(0x8000)

    assert coverage.executed[0x8000] == 1
    assert not any(coverage.executed_in_bank(3))


def test_the_flat_map_is_unchanged_by_any_of_this():
    """Everything already built on coverage -- the panel, count(), ranges() -- keeps
    working, and a 48K session is untouched."""
    coverage = CoverageMap()
    coverage.select_bank(2)
    coverage.mark(0x9000)
    coverage.mark(0xC000)

    assert coverage.count() == 2
    assert coverage.executed[0x9000] == 1 and coverage.executed[0xC000] == 1


def test_a_machine_that_never_pages_allocates_nothing():
    coverage = CoverageMap()
    coverage.mark(0xC123)

    assert coverage.bank_executed == {}
    assert coverage.executed[0xC123] == 1


def test_clearing_keeps_following_the_live_mapping():
    """Clear must not leave the map recording into a bank that is no longer mapped."""
    coverage = CoverageMap()
    coverage.select_bank(5)
    coverage.mark(0xC000)

    coverage.clear()
    coverage.mark(0xC001)

    assert coverage.executed_in_bank(5)[0x0000] == 0     # the old marks are gone
    assert coverage.executed_in_bank(5)[0x0001] == 1     # ...but bank 5 is still current


# --- wired to a real machine -----------------------------------------------------

@pytest.fixture
def paged():
    machine = build_machine("128k")
    return machine, EmulatorController(machine)


def test_the_controller_follows_the_machines_paging(paged):
    machine, controller = paged
    assert controller.coverage.current_bank == 0      # the power-on mapping, recorded

    machine.set_paging(0x06)

    assert controller.coverage.current_bank == 6


def test_paging_from_emulated_code_is_followed_too(paged):
    """A program pages by writing port 0x7FFD, not by calling set_paging -- so the
    listener has to be reached through the IO path as well."""
    machine, controller = paged
    machine._io_write(0x7FFD, 0x04)

    assert controller.coverage.current_bank == 4


def test_swapping_the_machine_rebinds_the_listener(paged):
    """The trap every other view in this window has fallen into at least once: the
    listener was attached to the *old* machine and would report a dead mapping."""
    _machine, controller = paged
    replacement = build_machine("128k")

    controller.set_machine(replacement)
    replacement.set_paging(0x07)

    assert replacement.paging_listener is not None
    assert controller.coverage.current_bank == 7


def test_a_48k_machine_needs_no_listener_and_gets_none():
    machine = build_machine("48k")
    controller = EmulatorController(machine)

    assert not hasattr(machine, "paging_listener")
    assert controller.coverage.bank_executed == {}
