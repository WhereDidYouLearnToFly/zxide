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


def create_128k_memory(rom0_data: bytes, rom1_data: bytes):
    """Build the 128K memory: a bank *pool* plus its power-on mapping.

    Unlike the fixed 48K map, the 128K pages banks in and out of the four slots via
    port 0x7FFD, so the banks must outlive whatever is currently mapped. We therefore
    return the pool alongside the initial ``Memory`` so the machine can keep
    references and swap them with ``Memory.page``:

        (memory, rom_banks, ram_banks)

    - ``ram_banks``: eight 16K RAM banks (0-7). The odd banks (1, 3, 5, 7) are
      contended on real hardware -- they share the memory bus with the ULA.
    - ``rom_banks``: two 16K ROMs -- ROM 0 is the 128 editor/menu, ROM 1 is 48 BASIC.
    - Power-on map (0x7FFD = 0): ROM0 at 0x0000, RAM5 (the normal screen) at 0x4000,
      RAM2 at 0x8000, RAM0 at 0xC000. Slots 1 and 2 never change; paging only ever
      swaps ROM into slot 0 and a RAM bank into slot 3.
    """
    ram_banks = [Bank(contended=(n in (1, 3, 5, 7))) for n in range(8)]
    rom_banks = [
        Bank.from_bytes(rom0_data, readonly=True),
        Bank.from_bytes(rom1_data, readonly=True),
    ]
    memory = Memory([rom_banks[0], ram_banks[5], ram_banks[2], ram_banks[0]])
    return memory, rom_banks, ram_banks
