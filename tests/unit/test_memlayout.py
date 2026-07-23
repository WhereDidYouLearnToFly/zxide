"""Tests for the free-space / placement model (zxemu_core.memlayout)."""

from __future__ import annotations

import pytest

from zxemu_core.memlayout import FreeSpaceIndex, bank_ids_for_model
from zxemu_core.memory import BANK_SIZE, SCREEN_BYTES


def test_bank_ids_for_48k():
    assert bank_ids_for_model("48k") == ["rom", "ram1", "ram2", "ram3"]


def test_bank_ids_for_128k():
    assert bank_ids_for_model("128k") == ["rom0", "rom1"] + [f"ram{n}" for n in range(8)]


def test_rom_is_fully_reserved():
    index = FreeSpaceIndex("48k")
    assert index.free_ranges("rom") == []
    with pytest.raises(ValueError, match="overlaps"):
        index.place("rom", 0, 1)


def test_screen_bank_reserves_its_first_bytes_on_48k():
    index = FreeSpaceIndex("48k")
    free = index.free_ranges("ram1")
    assert free == [(SCREEN_BYTES, BANK_SIZE - SCREEN_BYTES)]


def test_both_screen_banks_reserved_on_128k():
    index = FreeSpaceIndex("128k")
    assert index.free_ranges("ram5") == [(SCREEN_BYTES, BANK_SIZE - SCREEN_BYTES)]
    assert index.free_ranges("ram7") == [(SCREEN_BYTES, BANK_SIZE - SCREEN_BYTES)]


def test_non_screen_ram_bank_starts_fully_free():
    index = FreeSpaceIndex("48k")
    assert index.free_ranges("ram2") == [(0, BANK_SIZE)]


def test_place_splits_free_ranges():
    index = FreeSpaceIndex("48k")
    index.place("ram2", 100, 50)
    assert index.free_ranges("ram2") == [(0, 100), (150, BANK_SIZE - 150)]


def test_place_rejects_overlap():
    index = FreeSpaceIndex("48k")
    index.place("ram2", 100, 50)
    with pytest.raises(ValueError, match="overlaps"):
        index.place("ram2", 120, 10)


def test_place_rejects_out_of_bank_bounds():
    index = FreeSpaceIndex("48k")
    with pytest.raises(ValueError, match="doesn't fit"):
        index.place("ram2", BANK_SIZE - 10, 20)


def test_place_rejects_unknown_bank():
    index = FreeSpaceIndex("48k")
    with pytest.raises(ValueError, match="unknown bank"):
        index.place("ram9", 0, 10)


def test_auto_locate_never_chooses_rom():
    index = FreeSpaceIndex("48k")
    # Fill every RAM bank almost entirely, leaving only ROM with any theoretical "room"
    # (which auto_locate must still refuse, since ROM never has real free ranges).
    for bank in ("ram1", "ram2", "ram3"):
        for start, length in index.free_ranges(bank):
            index.place(bank, start, length)
    assert index.auto_locate(1) is None


def test_auto_locate_prefers_non_screen_ram_before_screen_leftovers():
    index = FreeSpaceIndex("48k")
    result = index.auto_locate(10)
    assert result[0] == "ram2"  # first non-screen RAM bank in default search order


def test_auto_locate_falls_back_to_screen_bank_leftover_space():
    index = FreeSpaceIndex("48k")
    for bank in ("ram2", "ram3"):
        for start, length in index.free_ranges(bank):
            index.place(bank, start, length)
    result = index.auto_locate(10)
    assert result[0] == "ram1"
    assert result[1] == SCREEN_BYTES


def test_auto_locate_places_the_asset_so_it_wont_be_offered_twice():
    index = FreeSpaceIndex("48k")
    first = index.auto_locate(100)
    second = index.auto_locate(100)
    assert first != second


def test_auto_locate_returns_none_when_nothing_fits():
    index = FreeSpaceIndex("48k")
    assert index.auto_locate(BANK_SIZE * 10) is None
