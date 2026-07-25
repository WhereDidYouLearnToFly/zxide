"""Load ZX Spectrum ``.z80`` snapshot files into a Machine.

``.z80`` is the format most emulators and archives settled on, and unlike ``.sna`` it
is *versioned*, *compressed*, and records which machine it came from. Three versions
exist and all three are still in the wild, so all three are read here:

* **v1** -- a flat 30-byte header then the 48K RAM image ($4000-$FFFF), optionally
  compressed. 48K only; the format had no way to describe anything else.
* **v2 / v3** -- the same 30-byte header with PC zeroed (that zero *is* the version
  marker) followed by an extra header whose length says which version it is: 23 bytes
  for v2, 54 or 55 for v3. The extra header names the hardware, carries the real PC,
  the 0x7FFD paging byte and the AY's register state. RAM then arrives as a series of
  independently-compressed 16K pages, each tagged with the page it belongs to.

**Compression** is a single run-length escape: ``ED ED count value``. Only runs of five
or more are encoded (two or more if the byte is itself ``ED``), and a lone ``ED`` is
literal -- which is why the decoder has to look at the byte *after* an ``ED`` before
deciding. A v1 image ends with the marker ``00 ED ED 00``; v2/v3 pages instead carry an
explicit length, and the special length 0xFFFF means "not compressed, exactly 16384
bytes follow".

Loading is deliberately strict about the machine: a 128K snapshot needs the 128K
machine and a 48K one needs the 48K machine, the same rule ``snapshot.py`` applies,
because silently loading half a machine's RAM produces a plausible-looking image that
crashes later for no visible reason.
"""

from __future__ import annotations

V1_HEADER_SIZE = 30
PAGE_SIZE = 0x4000
V1_END_MARKER = bytes([0x00, 0xED, 0xED, 0x00])

# Hardware-mode byte (extra header offset 34). Its meaning depends on the version --
# the same value 3 means "128K" in v2 but "48K + M.G.T." in v3, a genuine trap in the
# format. Anything not listed is rejected by name rather than guessed at.
_MODE_48K = "48k"
_MODE_128K = "128k"
_V2_MODES = {0: _MODE_48K, 1: _MODE_48K, 2: "SamRam", 3: _MODE_128K, 4: _MODE_128K}
_V3_MODES = {
    0: _MODE_48K, 1: _MODE_48K, 2: "SamRam", 3: _MODE_48K,
    4: _MODE_128K, 5: _MODE_128K, 6: _MODE_128K,
    7: "+3", 9: _MODE_128K, 10: "Scorpion", 11: "Didaktik",
    12: _MODE_128K, 13: "+2A", 14: "TC2048", 15: "TC2068", 128: "TS2068",
}
# Pentagon (9) and +2 (12) are 128K-compatible for our purposes: same paging port, same
# two ROMs as far as a snapshot's RAM contents are concerned.

# Where a page number lands. In 48K mode the pages map to fixed addresses; in 128K mode
# page n is simply RAM bank n-3 (so pages 3..10 are banks 0..7).
_48K_PAGE_TO_SLOT = {4: 2, 5: 3, 8: 1}  # 0x8000, 0xC000, 0x4000


def _word(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def load_z80(machine, data: bytes) -> None:
    """Restore a ``.z80`` snapshot (v1, v2 or v3) into ``machine``."""
    if len(data) < V1_HEADER_SIZE:
        raise ValueError(f"not a .z80: only {len(data)} bytes")

    is_128k_machine = hasattr(machine, "ram_banks")
    pc = _word(data, 6)
    if pc != 0:  # v1: the header's PC is real, and the file is 48K by definition
        _load_registers(machine, data)
        machine.cpu.regs.pc = pc
        if is_128k_machine:
            raise ValueError("a 48K .z80 snapshot cannot be loaded into the 128K machine")
        compressed = bool(data[12] & 0x20)
        image = _decompress_v1(data[V1_HEADER_SIZE:]) if compressed else data[V1_HEADER_SIZE:]
        _write_48k_image(machine, image)
        return

    extra_length = _word(data, V1_HEADER_SIZE)
    if extra_length not in (23, 54, 55):
        raise ValueError(f"unknown .z80 extra header length {extra_length} (not v2 or v3)")
    modes = _V2_MODES if extra_length == 23 else _V3_MODES
    mode_byte = data[34]
    model = modes.get(mode_byte)
    if model is None:
        raise ValueError(f"unsupported .z80 hardware mode {mode_byte}")
    if model not in (_MODE_48K, _MODE_128K):
        raise ValueError(f"unsupported machine in .z80: {model}")
    if model == _MODE_128K and not is_128k_machine:
        raise NotImplementedError("a 128K .z80 snapshot needs the 128K machine")
    if model == _MODE_48K and is_128k_machine:
        raise ValueError("a 48K .z80 snapshot cannot be loaded into the 128K machine")

    _load_registers(machine, data)
    machine.cpu.regs.pc = _word(data, 32)

    # Pages start after the 30-byte header, the 2-byte length field, and the extra header.
    offset = V1_HEADER_SIZE + 2 + extra_length
    while offset + 3 <= len(data):
        length = _word(data, offset)
        page = data[offset + 2]
        offset += 3
        if length == 0xFFFF:  # the "stored raw" sentinel
            block, offset = data[offset:offset + PAGE_SIZE], offset + PAGE_SIZE
        else:
            block, offset = _decompress(data[offset:offset + length]), offset + length
        _write_page(machine, page, block, is_128k=model == _MODE_128K)

    if model == _MODE_128K:
        # Paging last: the banks must already hold their data before we choose which one
        # is visible, and set_paging also picks the screen the ULA will draw.
        machine.set_paging(data[35], force=True)
        _restore_ay(machine, data)


def _load_registers(machine, data: bytes) -> None:
    """The 30-byte header common to every version (PC excepted -- callers set that)."""
    regs = machine.cpu.regs
    regs.a = data[0]
    regs.f = data[1]
    regs.bc = _word(data, 2)
    regs.hl = _word(data, 4)
    regs.sp = _word(data, 8)
    regs.i = data[10]
    flags1 = data[12]
    if flags1 == 255:
        flags1 = 1  # a documented quirk: 255 here means 1 (some old files store it that way)
    # R is 7 bits in its own byte; its top bit rides in flags1 bit 0.
    regs.r = (data[11] & 0x7F) | ((flags1 & 0x01) << 7)
    regs.de = _word(data, 13)
    regs.bc2 = _word(data, 15)
    regs.de2 = _word(data, 17)
    regs.hl2 = _word(data, 19)
    regs.a2 = data[21]
    regs.f2 = data[22]
    regs.iy = _word(data, 23)
    regs.ix = _word(data, 25)
    regs.iff1 = bool(data[27])
    regs.iff2 = bool(data[28])
    regs.im = data[29] & 0x03
    machine.ula.border_color = (flags1 >> 1) & 0x07


def _restore_ay(machine, data: bytes) -> None:
    """Put the AY back the way it was: 16 register values, then the selected register.

    Without this a snapshot taken mid-tune resumes with a silent (or wrongly tuned)
    chip until the music player happens to rewrite every register.
    """
    ay = getattr(machine, "ay", None)
    if ay is None:
        return
    for reg in range(16):
        ay.select_register(reg)
        ay.write_selected(0, data[39 + reg])
    ay.select_register(data[38] & 0x0F)


def _write_48k_image(machine, image: bytes) -> None:
    """Write a flat 48K RAM image ($4000-$FFFF) into slots 1-3."""
    if len(image) < 3 * PAGE_SIZE:
        raise ValueError(f"truncated 48K .z80 image: {len(image)} bytes, expected {3 * PAGE_SIZE}")
    for slot in (1, 2, 3):
        start = (slot - 1) * PAGE_SIZE
        machine.memory.slots[slot].data[:] = image[start:start + PAGE_SIZE]


def _write_page(machine, page: int, block: bytes, *, is_128k: bool) -> None:
    """Place one 16K page. Pages we don't emulate (ROM images, Interface I) are dropped."""
    if len(block) != PAGE_SIZE:
        raise ValueError(f"page {page} is {len(block)} bytes, expected {PAGE_SIZE}")
    if is_128k:
        bank = page - 3
        if 0 <= bank <= 7:
            machine.ram_banks[bank].data[:] = block
        return  # pages 0-2 are ROM/Interface I images -- nothing to restore into
    slot = _48K_PAGE_TO_SLOT.get(page)
    if slot is not None:
        machine.memory.slots[slot].data[:] = block


def _decompress(data: bytes) -> bytes:
    """Expand ``ED ED count value`` runs. A lone ED, or ED at the very end, is literal."""
    out = bytearray()
    i = 0
    end = len(data)
    while i < end:
        byte = data[i]
        if byte == 0xED and i + 1 < end and data[i + 1] == 0xED:
            if i + 3 >= end:  # a truncated run: nothing sensible to expand, keep it literal
                out += data[i:]
                break
            out += bytes([data[i + 3]]) * data[i + 2]
            i += 4
        else:
            out.append(byte)
            i += 1
    return bytes(out)


def _decompress_v1(data: bytes) -> bytes:
    """v1 has no length field: the image runs to the ``00 ED ED 00`` end marker."""
    end = data.find(V1_END_MARKER)
    return _decompress(data if end < 0 else data[:end])
