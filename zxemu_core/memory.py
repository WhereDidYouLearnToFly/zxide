"""Paged memory model: four 16K address slots, each backed by a swappable bank.

Spectrum48 wires this statically (one ROM bank, three RAM banks). The
page()/is_contended() interface is the hook a future Spectrum128 subclass
will use to implement port 0x7ffd paging without reworking this module.
"""

from __future__ import annotations

BANK_SIZE = 0x4000  # 16K
SLOT_COUNT = 4


class Bank:
    """A single 16K block of memory (ROM or RAM)."""

    def __init__(self, size: int = BANK_SIZE, *, readonly: bool = False, contended: bool = False):
        self.data = bytearray(size)
        self.readonly = readonly
        self.contended = contended

    @classmethod
    def from_bytes(cls, data: bytes, *, readonly: bool = False, contended: bool = False) -> "Bank":
        if len(data) != BANK_SIZE:
            raise ValueError(f"bank data must be {BANK_SIZE} bytes, got {len(data)}")
        bank = cls(readonly=readonly, contended=contended)
        bank.data[:] = data
        return bank


class Memory:
    """64K address space split into four 16K slots, each holding a Bank."""

    def __init__(self, slots: list[Bank]):
        if len(slots) != SLOT_COUNT:
            raise ValueError(f"expected {SLOT_COUNT} slots, got {len(slots)}")
        self.slots: list[Bank] = list(slots)

    def page(self, slot: int, bank: Bank) -> None:
        self.slots[slot] = bank

    def _locate(self, address: int) -> tuple[Bank, int]:
        address &= 0xFFFF
        slot_index, offset = divmod(address, BANK_SIZE)
        return self.slots[slot_index], offset

    def read_byte(self, address: int) -> int:
        bank, offset = self._locate(address)
        return bank.data[offset]

    def write_byte(self, address: int, value: int) -> None:
        bank, offset = self._locate(address)
        if bank.readonly:
            return
        bank.data[offset] = value & 0xFF

    def read_word(self, address: int) -> int:
        lo = self.read_byte(address)
        hi = self.read_byte((address + 1) & 0xFFFF)
        return lo | (hi << 8)

    def write_word(self, address: int, value: int) -> None:
        self.write_byte(address, value & 0xFF)
        self.write_byte((address + 1) & 0xFFFF, (value >> 8) & 0xFF)

    def is_contended(self, address: int) -> bool:
        bank, _ = self._locate(address)
        return bank.contended


def create_48k_memory(rom_data: bytes) -> Memory:
    """Build the fixed (unpaged) Spectrum48 memory map.

    Slot 0 (0x0000-0x3FFF): 16K ROM, uncontended.
    Slot 1 (0x4000-0x7FFF): 16K RAM containing the screen, contended.
    Slot 2 (0x8000-0xBFFF): 16K RAM, uncontended.
    Slot 3 (0xC000-0xFFFF): 16K RAM, uncontended.
    """
    rom_bank = Bank.from_bytes(rom_data, readonly=True, contended=False)
    screen_bank = Bank(contended=True)
    ram_bank_2 = Bank(contended=False)
    ram_bank_3 = Bank(contended=False)
    return Memory([rom_bank, screen_bank, ram_bank_2, ram_bank_3])
