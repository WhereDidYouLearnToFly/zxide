import importlib.resources as res

import pytest

from zxemu_core.memory import Bank, BANK_SIZE, Memory, create_48k_memory


def make_ram_only_memory():
    return Memory([Bank(), Bank(), Bank(), Bank()])


def test_bank_from_bytes_wrong_size_raises():
    with pytest.raises(ValueError):
        Bank.from_bytes(b"\x00" * (BANK_SIZE - 1))


def test_read_write_ram_byte():
    memory = make_ram_only_memory()
    memory.write_byte(0x8000, 0x42)
    assert memory.read_byte(0x8000) == 0x42


def test_write_wraps_to_8_bits():
    memory = make_ram_only_memory()
    memory.write_byte(0x8000, 0x142)
    assert memory.read_byte(0x8000) == 0x42


def test_read_write_word_little_endian():
    memory = make_ram_only_memory()
    memory.write_word(0xC000, 0xBEEF)
    assert memory.read_byte(0xC000) == 0xEF
    assert memory.read_byte(0xC001) == 0xBE
    assert memory.read_word(0xC000) == 0xBEEF


def test_word_write_wraps_across_slot_boundary():
    memory = make_ram_only_memory()
    memory.write_word(0xFFFF, 0x1234)
    assert memory.read_byte(0xFFFF) == 0x34
    assert memory.read_byte(0x0000) == 0x12


def test_rom_bank_is_write_protected():
    rom_bank = Bank.from_bytes(b"\xAA" * BANK_SIZE, readonly=True)
    memory = Memory([rom_bank, Bank(), Bank(), Bank()])
    memory.write_byte(0x0000, 0xFF)
    assert memory.read_byte(0x0000) == 0xAA


def test_is_contended_reflects_bank():
    memory = Memory([
        Bank(contended=False),
        Bank(contended=True),
        Bank(contended=False),
        Bank(contended=False),
    ])
    assert memory.is_contended(0x0000) is False
    assert memory.is_contended(0x4000) is True
    assert memory.is_contended(0x7FFF) is True
    assert memory.is_contended(0x8000) is False


def _load_48_rom_bytes() -> bytes:
    rom_path = res.files("zxemu_core") / "roms" / "48.rom"
    return rom_path.read_bytes()


def test_create_48k_memory_loads_rom():
    memory = create_48k_memory(_load_48_rom_bytes())
    # 48K ROM starts with DI; AF 11 FF FF; JP 0x11CB (known first bytes).
    assert memory.read_byte(0x0000) == 0xF3
    assert memory.read_byte(0x0001) == 0xAF
    assert memory.read_byte(0x0005) == 0xC3  # JP opcode
    assert memory.read_word(0x0006) == 0x11CB  # JP target address operand


def test_create_48k_memory_rom_is_protected_and_ram_is_writable():
    memory = create_48k_memory(_load_48_rom_bytes())
    memory.write_byte(0x0000, 0x00)
    assert memory.read_byte(0x0000) == 0xF3  # ROM write ignored

    memory.write_byte(0x4000, 0x55)  # screen RAM
    assert memory.read_byte(0x4000) == 0x55
    assert memory.is_contended(0x4000) is True

    memory.write_byte(0xC000, 0x77)
    assert memory.read_byte(0xC000) == 0x77
    assert memory.is_contended(0xC000) is False
