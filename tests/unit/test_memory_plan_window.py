"""The memory plan window (zxemu_ui.panels.memory_plan_window).

What matters here is what the to-scale dock could not do: show every bank rather than the
four currently paged in, give every block the same readable height whatever its size, and
state the free space between blocks without ever calling occupied bytes free.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication, QLabel  # noqa: E402

from zxemu_core.debug.asm_layout import Region  # noqa: E402
from zxemu_ui.panels.memory_plan_window import (  # noqa: E402
    ROW_HEIGHT,
    MemoryPlanWindow,
    bank_position,
    column_order,
    _BankColumn,
    _free_ranges,
    _RegionRow,
    _size_text,
)
from zxemu_ui.workspace.memory_plan import MemoryPlan  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _region(name, bank, offset, length, kind="code", slot=2):
    return Region(name=name, kind=kind, slot=slot, bank=bank, offset=offset, length=length,
                  address=0x8000 + offset, origin="main.asm", line=1)


def _rows(column):
    return [column.layout().itemAt(i).widget() for i in range(column.layout().count()) if column.layout().itemAt(i).widget() is not None]


# --- free space ----------------------------------------------------------------------


def test_free_ranges_are_the_gaps_between_claims():
    claims = [_region("a", "ram2", 0, 100), _region("b", "ram2", 500, 100)]
    assert _free_ranges("ram2", "48k", claims) == [(100, 400), (600, 16384 - 600)]


def test_overlapping_claims_never_make_occupied_bytes_look_free():
    """The exact case the window exists to show -- two blocks on the same bytes."""
    claims = [_region("a", "ram2", 0, 300), _region("b", "ram2", 200, 300)]
    assert _free_ranges("ram2", "48k", claims) == [(500, 16384 - 500)]


def test_hardware_reserved_space_is_not_offered_as_free():
    """The 48K screen sits at the base of RAM1 and was never available."""
    assert _free_ranges("ram1", "48k", []) == [(6912, 16384 - 6912)]


def test_a_full_bank_reports_no_free_space():
    assert _free_ranges("ram2", "48k", [_region("all", "ram2", 0, 16384)]) == []


# --- the columns ---------------------------------------------------------------------


def test_a_bank_column_interleaves_blocks_and_gaps_in_address_order(qapp):
    window = MemoryPlanWindow()
    claims = [_region("first", "ram2", 0, 100), _region("second", "ram2", 500, 100)]
    column = _BankColumn("ram2", "48k", claims, {}, window)
    texts = [widget.findChild(QLabel).text() for widget in _rows(column) if not isinstance(widget, QLabel)]
    assert texts[0] == "first"
    assert "free" in texts[1]
    assert texts[2] == "second"


def test_every_block_is_the_same_height_whatever_its_size(qapp):
    window = MemoryPlanWindow()
    claims = [_region("tiny", "ram2", 0, 43), _region("huge", "ram2", 1000, 6912)]
    column = _BankColumn("ram2", "48k", claims, {}, window)  # held, or Qt frees its rows
    rows = [widget for widget in _rows(column) if isinstance(widget, _RegionRow)]
    assert [row.height() for row in rows] == [ROW_HEIGHT, ROW_HEIGHT]


def test_a_block_states_where_it_starts_and_ends(qapp):
    window = MemoryPlanWindow()
    row = _RegionRow(_region("attribs", "ram2", 0x300, 348), 0x8000, True, False, window)
    detail = [label.text() for label in row.findChildren(QLabel)][1]
    assert detail.startswith("$8300 - $845B")
    assert "348 b" in detail


def test_an_estimated_length_says_so(qapp):
    """A leading ~ on the size, and the full explanation in the tooltip -- eleven
    characters of "(estimate)" per row is the difference between eight banks fitting
    on screen and not."""
    window = MemoryPlanWindow()
    region = _region("guessy", "ram2", 0, 100)
    region.estimated = True
    row = _RegionRow(region, 0x8000, True, False, window)
    assert "~100 b" in [label.text() for label in row.findChildren(QLabel)][1]
    assert "estimated" in row.toolTip()


def test_an_immovable_block_is_not_draggable(qapp):
    window = MemoryPlanWindow()
    row = _RegionRow(_region("fixed", "ram2", 0, 100), 0x8000, False, False, window)
    assert not row.movable
    assert "fixed" in row.toolTip()


# --- the window ----------------------------------------------------------------------


def _plan(*regions):
    plan = MemoryPlan()
    plan.regions = list(regions)
    return plan


def test_only_banks_with_content_are_shown_by_default(qapp):
    window = MemoryPlanWindow()
    window.set_plan(_plan(_region("a", "ram2", 0, 100)), "48k", {})
    headers = [label.text() for label in window.findChildren(QLabel) if label.text().startswith("RAM")]
    assert headers == ["RAM2"]


def test_showing_empty_banks_reveals_every_bank_the_machine_has(qapp):
    """A 128K has eight RAM banks; you can assemble into one that is not paged in."""
    window = MemoryPlanWindow()
    window.set_plan(_plan(_region("a", "ram2", 0, 100)), "128k", {})
    window._show_empty.setChecked(True)
    headers = [label.text() for label in window.findChildren(QLabel) if label.text().startswith("RAM")]
    assert len(headers) == 8


def test_a_bank_that_is_not_paged_in_still_gets_a_column(qapp):
    """RAM7 is nowhere in the four slots at boot, but code can still be assembled into it."""
    window = MemoryPlanWindow()
    window.set_plan(_plan(_region("shadow", "ram7", 0x100, 512, slot=3)), "128k", {})
    headers = [label.text() for label in window.findChildren(QLabel) if label.text().startswith("RAM")]
    assert headers == ["RAM7"]


def test_the_summary_counts_blocks_banks_and_conflicts(qapp):
    window = MemoryPlanWindow()
    window.set_plan(_plan(_region("a", "ram2", 0, 100), _region("b", "ram3", 0, 100, slot=3)), "48k", {})
    assert "2 blocks in 2 banks" in window._summary.text()
    assert "no conflicts" in window._summary.text()


def test_moving_within_a_bank_is_emitted(qapp):
    window = MemoryPlanWindow()
    region = _region("a", "ram2", 0, 100)
    moves = []
    window.region_moved.connect(lambda moved, address: moves.append((moved.name, address)))
    window.move(region, 0x8400, "ram2")
    assert moves == [("a", 0x8400)]


def test_moving_across_banks_carries_the_target_bank(qapp):
    """An address does not imply a bank: on a 128K, six of the eight share slot 3."""
    window = MemoryPlanWindow()
    window.set_plan(_plan(_region("a", "ram2", 0, 100)), "128k", {})
    moves = []
    window.region_moved.connect(lambda moved, address, bank: moves.append((address, bank)))
    window.move(_region("a", "ram2", 0, 100), 0xC000, "ram3")
    assert moves == [(0xC000, "ram3")]


def test_columns_follow_the_machine_layout_not_the_bank_numbers():
    """The always-mapped 32K first, in address order, then the pool that needs $7FFD."""
    assert column_order("128k") == ["rom0", "rom1", "ram5", "ram2", "ram0", "ram1", "ram3", "ram4", "ram6", "ram7"]


def test_a_48k_needs_no_reordering_because_its_banks_are_its_slots():
    assert column_order("48k") == ["rom", "ram1", "ram2", "ram3"]


def test_a_header_says_whether_a_bank_is_always_there_or_has_to_be_paged():
    assert bank_position("ram5", "128k") == "slot 1 · always"
    assert bank_position("ram2", "128k") == "slot 2 · always"
    assert bank_position("ram7", "128k") == "slot 3 · when paged"
    assert bank_position("ram1", "48k") == "slot 1 · always"


def test_size_text_reads_as_bytes_then_kilobytes():
    assert (_size_text(43), _size_text(1024), _size_text(6912)) == ("43 b", "1K", "6.8K")
