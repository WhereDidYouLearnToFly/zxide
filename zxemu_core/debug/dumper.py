"""Memory to sources: turn a running program back into assembly you can rebuild.

zxide can already *inspect* somebody else's program -- disassembly, coverage,
cross-references. This module is the step that hands it back to you as **source**: RAM
becomes ``.asm`` you can read, set breakpoints in, annotate, change, and reassemble.
"Here is a game, here is its source, now step through it" is a considerably better place
to start from than an empty ``main.asm``.

The problem, and why it is not solved statically
------------------------------------------------
**Telling code from data is undecidable.** The same bytes are a valid instruction stream
*and* a valid bitmap, and no amount of staring at them settles it -- a disassembler asked
to decode a sprite will happily produce plausible nonsense, and produce it confidently.

So this module does not decide statically. **Coverage is the ground truth**: an address
the CPU executed *is* code, observed rather than inferred. Run the program, exercise the
parts you care about, and the addresses that ran become disassembly while everything else
stays data. The corollary matters as much: an address with no coverage means *"not yet"*,
never *"never"*, so the dump gets better the more of the program you have exercised.

Why leaving something as data is a safe answer
----------------------------------------------
A region emitted as bytes still assembles to exactly the right bytes and still runs. You
merely have a blob you have not understood yet. That is what makes the whole approach
safe to build incrementally: the all-data dump is not a lesser version waiting to be
replaced, it is the other half of the same classifier, and it is *correct* on its own.

The invariant that makes any of this trustworthy
-------------------------------------------------
**Assemble the dump and compare the bytes with the memory it came from.** Byte-identical
means the source provably represents the program. Everything here is arranged so that
check is possible and cheap:

* regions **tile the dumped address range exactly** -- every byte accounted for once, no
  gaps and no overlaps (:func:`check_regions_tile`, asserted in the tests);
* a code region's instruction lengths sum to exactly its size, so a disassembly can never
  silently run past its end or stop short.

Get those wrong and the output still *looks* fine; the assembler is what notices.

What this module deliberately does not do
------------------------------------------
It emits no Qt, touches no files, and knows nothing about projects: it turns memory plus a
coverage map into text. Writing that text out as a buildable zxide project is
``zxemu_ui/workspace/dump_project.py``'s job. The split is the same one ``assets/`` uses
in the opposite direction -- that package places things *into* memory, this one pulls them
back out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .disassembler import disassemble_one

#: Where RAM starts. The ROM below this is not yours to dump -- it is the same 16K on
#: every machine, zxide ships it, and emitting it would be both wrong and enormous.
RAM_BASE = 0x4000
ADDRESS_SPACE = 0x10000

CODE = "code"
DATA = "data"

#: Data regions at or above this size are written as a binary file and ``incbin``'d;
#: smaller ones are spelled out as ``db`` lines. The trade is readability against bulk:
#: 40K of ``db`` is unreadable and slow to assemble, while a small table is exactly the
#: thing you want in front of you when annotating -- and annotating is the point.
INCBIN_THRESHOLD = 256

#: Bytes per ``db`` line. Eight keeps a line inside a narrow editor pane and makes the
#: hex easy to count against a memory view.
DB_BYTES_PER_LINE = 8


@dataclass(frozen=True)
class Region:
    """One contiguous stretch of memory, classified.

    ``end`` is exclusive, matching Python's slice convention, because every off-by-one in
    this module would otherwise be a byte added to or lost from the rebuilt program.
    """

    start: int
    end: int
    kind: str          # CODE or DATA
    bank: str = "ram"  # which bank it came from; meaningful on 128K/Pentagon

    @property
    def size(self) -> int:
        return self.end - self.start

    @property
    def label(self) -> str:
        """A stable, sjasmplus-safe name derived from where it lives."""
        return "{}_{:04x}".format(self.bank, self.start)


@dataclass
class Dump:
    """A planned dump: the regions, and the labels worth naming inside them."""

    regions: list[Region] = field(default_factory=list)
    labels: dict[int, str] = field(default_factory=dict)
    start_address: int | None = None   # where execution should resume (PC at dump time)

    @property
    def code_bytes(self) -> int:
        return sum(r.size for r in self.regions if r.kind == CODE)

    @property
    def data_bytes(self) -> int:
        return sum(r.size for r in self.regions if r.kind == DATA)


def plan_regions(coverage_executed, start: int = RAM_BASE, end: int = ADDRESS_SPACE,
                 bank: str = "ram", minimum_code_run: int = 4,
                 memory=None) -> list[Region]:
    """Split ``[start, end)`` into alternating code and data regions.

    ``coverage_executed`` is the flat per-address flag array from
    :class:`~zxemu_core.debug.analysis.CoverageMap` (or None for "nothing was executed",
    which yields a single data region -- the correct all-data dump).

    **Pass ``memory``.** Coverage marks the address an instruction *starts* at, not every
    byte it occupies, so executed code leaves a *sparse* trail: ``ld a,7 / out ($fe),a /
    ret`` marks 0xC000, 0xC002 and 0xC004 and leaves 0xC001 and 0xC003 unmarked. Treating
    only consecutive marks as a run therefore shreds real code into two-byte fragments
    that all fall below ``minimum_code_run`` and come out as data. With ``memory``, each
    marked address is expanded to the whole instruction it begins, which is what the
    coverage actually means.

    (This was found the hard way: the early tests set coverage as a solid range of
    addresses, which no real program ever produces, and the bug only surfaced against a
    machine that had genuinely executed something.)

    ``minimum_code_run`` discards very short executed runs -- a jump landing in the middle
    of a data table through a computed address, a single byte reached by a fluke -- which
    would otherwise carve a scrap of "code" out of the middle of a bitmap. Short runs stay
    data, which is always a safe answer.
    """
    if coverage_executed is None:
        return [Region(start, end, DATA, bank)] if end > start else []

    regions: list[Region] = []
    cursor = start
    for run_start, run_end in _executed_runs(coverage_executed, start, end, memory):
        if run_end - run_start < minimum_code_run:
            continue
        if run_start > cursor:
            regions.append(Region(cursor, run_start, DATA, bank))
        regions.append(Region(run_start, max(run_end, cursor), CODE, bank))
        cursor = run_end
    if cursor < end:
        regions.append(Region(cursor, end, DATA, bank))
    return regions


def _executed_runs(executed, start: int, end: int, memory=None):
    """Executed addresses in ``[start, end)`` collapsed into (start, end) runs.

    With ``memory``, a marked address covers the whole instruction that begins there --
    see :func:`plan_regions` for why that is what coverage means rather than a refinement
    of it. Without it, only the marked bytes themselves count, which is right for callers
    that already hold a dense map.
    """
    run_start = None
    reach = start                      # how far the current run extends, instructions included
    address = start
    while address < end:
        marked = address < len(executed) and executed[address]
        if marked:
            length = 1
            if memory is not None:
                _text, length = disassemble_one(memory, address)
                length = max(1, length)
            if run_start is None:
                run_start = address
            reach = max(reach, min(address + length, end))
        elif run_start is not None and address >= reach:
            yield run_start, reach
            run_start = None
        address += 1
    if run_start is not None:
        yield run_start, max(reach, run_start + 1)


def check_regions_tile(regions: list[Region], start: int, end: int) -> None:
    """Raise unless the regions cover ``[start, end)`` exactly once each.

    The structural half of the byte-identity invariant, and the half that needs no
    assembler. A gap silently drops bytes from the rebuilt program and an overlap silently
    duplicates them; both produce output that looks entirely reasonable until sjasmplus
    is asked to reproduce the original. Cheap to check, so it is checked.
    """
    cursor = start
    for region in regions:
        if region.start != cursor:
            raise ValueError(
                "regions do not tile: expected the next region at ${:04X}, "
                "got ${:04X}".format(cursor, region.start)
            )
        if region.end <= region.start:
            raise ValueError("empty or reversed region at ${:04X}".format(region.start))
        cursor = region.end
    if cursor != end:
        raise ValueError("regions stop at ${:04X}, expected ${:04X}".format(cursor, end))


def render_data(memory, region: Region) -> list[str]:
    """A data region as ``db`` lines, with an address comment every line.

    The comment is not decoration: when you are comparing this against a memory view or a
    disassembly, the address is the only way to find your place in several hundred lines
    of hex.
    """
    lines = ["{}:".format(region.label)]
    for base in range(region.start, region.end, DB_BYTES_PER_LINE):
        chunk = [memory.read_byte(a) for a in range(base, min(base + DB_BYTES_PER_LINE, region.end))]
        body = ",".join("${:02x}".format(byte) for byte in chunk)
        lines.append("    db {}    ; ${:04x}".format(body, base))
    return lines


def region_bytes(memory, region: Region) -> bytes:
    return bytes(memory.read_byte(a) for a in range(region.start, region.end))


# --- code: disassembly, and the labels that make it readable ---------------------

#: Mnemonics whose operand is a destination the CPU jumps to. Only these produce labels.
#:
#: Restricting labels to *branch* targets is deliberate. A branch destination is
#: necessarily an instruction boundary -- the CPU went there and decoded it -- so a label
#: can always be placed exactly there. The tempting extra source, ``ld hl,$1234`` style
#: pointers, is not: those usually point into data, where there is no instruction
#: boundary to hang a label on and no way to name a byte halfway through a ``db`` line.
#: Data pointers stay as hex in v1; naming them is a job for the later analysis pass.
_BRANCH_MNEMONICS = ("call", "jp", "jr", "djnz")


def _branch_target(text: str) -> int | None:
    """The address a branch instruction goes to, or None if this isn't one.

    Reads the disassembler's own output rather than re-decoding the bytes: it already
    formats destinations as a four-digit ``$xxxx``, and parsing that is both simpler and
    guaranteed to agree with what will be printed.
    """
    mnemonic = text.split(None, 1)[0] if text else ""
    if mnemonic not in _BRANCH_MNEMONICS:
        return None
    marker = text.rfind("$")
    if marker < 0:
        return None
    digits = text[marker + 1:marker + 5]
    if len(digits) != 4:
        return None       # `jp (hl)` and friends have no literal destination
    try:
        return int(digits, 16)
    except ValueError:
        return None


#: ED-prefixed opcodes that are *duplicate* encodings of a canonical one. The Z80 decodes
#: several bit patterns to the same instruction, and a disassembler naturally prints the
#: canonical name -- at which point the original byte is unrecoverable, because an
#: assembler will emit the canonical encoding instead.
_ED_DUPLICATES = frozenset({
    0x4C, 0x54, 0x5C, 0x64, 0x6C, 0x74, 0x7C,   # neg      (canonical 0x44)
    0x55, 0x5D, 0x65, 0x6D, 0x75, 0x7D,         # retn     (canonical 0x45)
    0x4E, 0x66, 0x6E,                           # im 0     (canonical 0x46)
    0x76,                                       # im 1     (canonical 0x56)
    0x7E,                                       # im 2     (canonical 0x5E)
})


def _round_trips(memory, address: int, text: str, length: int) -> bool:
    """Whether re-assembling ``text`` would produce the same bytes it was decoded from.

    Disassembly is not injective, and that is fatal here: the dump is only worth anything
    if it rebuilds byte-for-byte. Two families lose information, both found by the
    byte-identity test rather than by reasoning:

    * **A redundant DD/FD prefix.** ``DD DE nn`` is ``sbc a,n`` with a pointless IX
      prefix in front: the CPU ignores it, the disassembler rightly does not mention it,
      and an assembler then emits two bytes where there were three. Everything after
      shifts by one -- which showed up as a *branch displacement* changing thirty bytes
      earlier, since the label had moved.
    * **Duplicate ED encodings.** Seven byte patterns mean ``neg``; print the name and
      the original pattern is gone.

    Neither is exotic: both turn up in the first kilobyte of the 48K ROM, because both
    are what ordinary *data* decodes to when a region is misclassified as code.
    """
    first = memory.read_byte(address)
    if first in (0xDD, 0xFD) and "ix" not in text and "iy" not in text:
        return False
    if first == 0xED and memory.read_byte(address + 1) in _ED_DUPLICATES:
        return False
    return True


def walk_code(memory, region: Region):
    """Yield ``(address, text, length)`` for each instruction in a code region.

    ``text`` of None means "emit this address as a raw byte and carry on from the next" --
    used both for an instruction that would straddle the region end and for one that
    would not survive a round trip. Falling back a single byte at a time is deliberate:
    the *next* decode starts one byte along and usually lands on something that does
    round-trip, so the damage stays local rather than derailing the rest of the region.

    Overrunning the region end is the one failure that breaks reassembly outright -- the
    following region would start mid-instruction and every byte after it would shift -- so
    that case is checked first.
    """
    address = region.start
    while address < region.end:
        text, length = disassemble_one(memory, address)
        if address + length > region.end or not _round_trips(memory, address, text, length):
            yield address, None, 1
            address += 1
            continue
        yield address, text, length
        address += length


class BankWindow:
    """Read a RAM bank as though it were paged into the top 16K, mapped or not.

    The disassembler works through ``read_byte``, and a bank that is paged *out* is not
    reachable through the machine's address space at all. On real hardware you would have
    to halt the CPU and page it in; here a bank is a bytearray, so a four-line adapter is
    the whole of it.

    Addresses wrap within the 16K window, which matters at the very top: an instruction
    that runs off the end of 0xFFFF would otherwise index past the array.
    """

    def __init__(self, bank_data, base: int = 0xC000):
        self.data = bank_data
        self.base = base

    def read_byte(self, address: int) -> int:
        return self.data[(address - self.base) & 0x3FFF]


def flags_for_bank(bank_flags, base: int = 0xC000) -> bytearray:
    """Lift a bank's 16K coverage flags into an address-space-shaped array.

    ``plan_regions`` indexes by absolute address, which is the right interface for the
    common case; a bank's own flags start at zero. Rather than complicate the planner
    with an offset, the flags are placed where they belong.
    """
    flags = bytearray(ADDRESS_SPACE)
    flags[base:base + len(bank_flags)] = bank_flags
    return flags


def collect_labels(memory, regions: list[Region], prefix: str = "") -> dict[int, str]:
    """Label every branch target that lands on an instruction boundary we will emit.

    Two passes, because a label is only safe to *use* if it is also going to be
    *defined*: the first records where instructions actually begin, the second keeps only
    those branch targets. A target inside a data region, or halfway through an
    instruction, is left as a bare address -- correct, if less readable, and it still
    assembles to the same bytes.
    """
    boundaries: set[int] = set()
    targets: set[int] = set()
    for region in regions:
        if region.kind != CODE:
            continue
        for address, text, _length in walk_code(memory, region):
            boundaries.add(address)
            if text is None:
                continue
            target = _branch_target(text)
            if target is not None:
                targets.add(target)

    labels = {region.start: region.label for region in regions}
    for target in sorted(targets):
        if target in boundaries and target not in labels:
            # The prefix exists for paged banks: the same address lives in all eight of
            # them, so an unqualified `Lc123` would be defined eight times over.
            labels[target] = "{}L{:04x}".format(prefix, target)
    return labels


def render_code(memory, region: Region, labels: dict[int, str],
                rom_names: dict[int, str] | None = None) -> list[str]:
    """A code region as assembly, with labels defined and branch destinations named.

    Substitution is purely textual, and safe for exactly one reason: a name is only
    substituted when it is defined at precisely the address it replaces, so the assembler
    resolves it to the identical value and the bytes cannot move.
    """
    rom_names = rom_names or {}
    lines: list[str] = []
    for address, text, _length in walk_code(memory, region):
        if address in labels:
            lines.append("{}:".format(labels[address]))
        if text is None:
            lines.append("    db ${:02x}"
                         "    ; ${:04x} (tail of region)".format(memory.read_byte(address), address))
            continue
        lines.append("    {}    ; ${:04x}".format(_with_names(text, labels, rom_names), address))
    return lines


def _with_names(text: str, labels: dict[int, str], rom_names: dict[int, str]) -> str:
    """Replace a branch destination with its label, if we have one for that exact address."""
    target = _branch_target(text)
    if target is None:
        return text
    name = labels.get(target) or rom_names.get(target)
    if name is None:
        return text
    return text[:text.rfind("$")] + name


def rom_symbols_used(memory, regions: list[Region]) -> dict[int, str]:
    """ROM routines this code calls, as ``{address: safe_label}``.

    The ROM is not dumped -- it is the same 16K on every machine and zxide ships it -- so
    these cannot be defined by the dump. They are emitted as ``equ`` constants instead,
    which turns ``call $0556`` into ``call LD_BYTES`` without changing a byte and tells
    you what the program is actually asking the machine to do.
    """
    from . import rom_symbols

    used: dict[int, str] = {}
    for region in regions:
        if region.kind != CODE:
            continue
        for _address, text, _length in walk_code(memory, region):
            if text is None:
                continue
            target = _branch_target(text)
            if target is None or target >= RAM_BASE:
                continue
            name = rom_symbols.name_for(target)
            if name:
                used[target] = _safe_label(name)
    return used


# --- restoring the machine, not just its memory ----------------------------------

#: A ``.sna``'s fixed sizes, which the writer below must hit exactly or no emulator will
#: load the result. Mirrors ``zxemu_core/storage/snapshot.py``, which is our reader.
SNA_48K_SIZE = 49179
SNA_128K_SIZE = 131103
SNA_HEADER_SIZE = 27
BANK_SIZE = 0x4000


def capture_state(machine) -> dict:
    """Everything about the machine that is *not* in RAM, and is needed to resume it.

    This is the whole reason the dumper needs more than an assembler. A memory image gets
    you the program's code and data; it does not get you the border colour, the interrupt
    mode, the ``I`` register, whether interrupts are even enabled, or a single CPU
    register. Restore RAM alone and a game comes up with a white border and -- far worse --
    an IM 2 handler that never fires, so it never reads the keyboard. It is running, and
    deaf.
    """
    regs = machine.cpu.regs
    paging = machine.paging_state() if hasattr(machine, "paging_state") else None
    return {
        "pc": regs.pc, "sp": regs.sp,
        "af": (regs.a << 8) | regs.f, "af2": (regs.a2 << 8) | regs.f2,
        "bc": regs.bc, "de": regs.de, "hl": regs.hl,
        "bc2": regs.bc2, "de2": regs.de2, "hl2": regs.hl2,
        "ix": (regs.ixh << 8) | regs.ixl, "iy": (regs.iyh << 8) | regs.iyl,
        "i": regs.i, "r": regs.r, "im": regs.im if regs.im in (0, 1, 2) else 1,
        "iff": bool(regs.iff1), "border": machine.ula.border_color & 0x07,
        "port_7ffd": paging.port_7ffd if paging else None,
        "ram_bank": paging.ram_bank if paging else None,
    }


def render_snapshot_lua(state: dict, paged: bool, filename: str) -> list[str]:
    """A ``LUA``/``ENDLUA`` block that writes the ``.sna`` itself, registers and all.

    **Why this rather than a restore stub.** sjasmplus's ``savesna`` (and
    ``zx.save_snapshot_sna``) take a filename and an entry address, and default every
    register -- which is what left a rebuilt game with a white border and no interrupts.
    The obvious repair is to emit Z80 that sets it all back, but that code has to *live in
    the program's own memory*: fifty-odd bytes, placed on the inference that a run of
    zeros nothing was seen to execute is unused. Coverage means "not yet", and a big run
    of zeros is very often a buffer the program has not filled yet, so the inference is
    exactly the kind that breaks something later and elsewhere.

    sjasmplus embeds Lua (5.4, since v1.20.0) with ``sj.get_byte`` to read assembled
    memory, ``sj.set_page`` to reach a bank, and the standard ``io`` library to write a
    file -- so the snapshot can simply be written correctly in the first place. Nothing is
    injected into the program at all.

    The cost falls out of the two formats:

    * **128K** stores PC in its extra header, so **not one byte of RAM is touched**.
    * **48K** has no PC field -- its loader ``RET``s to an address on the stack -- so two
      bytes must go at SP-2. That memory is below the stack pointer, which is unallocated
      by definition: the program overwrites it itself on its next push, call or interrupt.

    The block runs on the assembler's last pass, which is the only time ``sj.get_byte``
    returns real data (and requires ``DEVICE``, which the generated source always sets).
    """
    header = _sna_header_lua(state, paged)
    lines = [
        "; Write the snapshot ourselves, because `savesna` cannot carry the registers.",
        ";",
        "; A dump restores RAM. It does not restore the border, the interrupt mode, the I",
        "; register, whether interrupts are enabled, or any CPU register -- none of which",
        "; live in RAM. Without them a rebuilt game runs with a white border and, more to",
        "; the point, no interrupts at all, so it never reads the keyboard.",
        ";",
        "; sjasmplus embeds Lua and can read the assembled bytes back, so the .sna is",
        "; written here with a correct header. The alternative -- Z80 code that restores",
        "; the registers at run time -- would have to live in the program's own memory and",
        "; overwrite ~50 bytes of it. This costs nothing on 128K, and two bytes of dead",
        "; stack space on 48K (the format keeps PC on the stack, so there is no choice).",
        "    LUA",
        "        local out = {}",
        "        local function byte(v) out[#out+1] = string.char(v & 0xff) end",
        "        local function word(v) byte(v & 0xff) byte((v >> 8) & 0xff) end",
        "        local function block(from, to)",
        "            for a = from, to do out[#out+1] = string.char(sj.get_byte(a)) end",
        "        end",
        "",
    ]
    lines += ["        {}".format(line) for line in header]
    lines += [""]
    if paged:
        lines += [
            "        -- 128K: banks 5 and 2 are always mapped at 0x4000 and 0x8000; the",
            "        -- third block is whichever bank was in slot 3 when the dump was taken.",
            "        block(0x4000, 0x7fff)",
            "        block(0x8000, 0xbfff)",
            "        sj.set_slot(0xc000)",
            "        sj.set_page({})".format(state['ram_bank']),
            "        block(0xc000, 0xffff)",
            "        word(0x{:04x})   -- PC lives in the extra header here".format(state['pc']),
            "        byte(0x{:02x})   -- the paging latch".format(state['port_7ffd']),
            "        byte(0)      -- TR-DOS ROM flag",
            "        -- ...then every other bank, ascending.",
            "        for page = 0, 7 do",
            "            if page ~= 5 and page ~= 2 and page ~= {} then".format(state['ram_bank']),
            "                sj.set_page(page)",
            "                block(0xc000, 0xffff)",
            "            end",
            "        end",
            "        sj.set_page({})   -- leave the mapping as we found it".format(state['ram_bank']),
        ]
        expected = SNA_128K_SIZE
    else:
        lines += [
            "        -- 48K: no PC field. The loader RETs to an address on the stack, so PC",
            "        -- goes at SP-2 and the header points there. Those two bytes are below",
            "        -- the stack pointer, i.e. memory the program treats as scratch anyway.",
            "        block(0x4000, 0xffff)",
            "        local sp_slot = 0x{:04x} - 0x4000 + 1 + 27".format(state['sp'] - 2 & 65535),
            "        out[sp_slot]     = string.char(0x{:02x})".format(state['pc'] & 255),
            "        out[sp_slot + 1] = string.char(0x{:02x})".format(state['pc'] >> 8 & 255),
        ]
        expected = SNA_48K_SIZE
    lines += [
        "",
        "        local blob = table.concat(out)",
        "        if #blob ~= {} then".format(expected),
        "            sj.error(\"snapshot is \" .. #blob .. \" bytes, expected {}\")".format(expected),
        "        end",
        "        local f = assert(io.open(\"{}\", \"wb\"))".format(filename),
        "        f:write(blob)",
        "        f:close()",
        "    ENDLUA",
    ]
    return lines


def _sna_header_lua(state: dict, paged: bool) -> list[str]:
    """The 27-byte ``.sna`` header, in the order every emulator expects it.

    On 48K the stored SP is *two below* the real one, because the loader pops PC from
    there; on 128K the real SP is stored, since PC has a field of its own.
    """
    stored_sp = state["sp"] if paged else (state["sp"] - 2) & 0xFFFF
    return [
        "byte(0x{:02x})          -- I".format(state['i']),
        "word(0x{:04x})        -- HL'".format(state['hl2']),
        "word(0x{:04x})        -- DE'".format(state['de2']),
        "word(0x{:04x})        -- BC'".format(state['bc2']),
        "word(0x{:04x})        -- AF'".format(state['af2']),
        "word(0x{:04x})        -- HL".format(state['hl']),
        "word(0x{:04x})        -- DE".format(state['de']),
        "word(0x{:04x})        -- BC".format(state['bc']),
        "word(0x{:04x})        -- IY".format(state['iy']),
        "word(0x{:04x})        -- IX".format(state['ix']),
        "byte(0x{:02x})          -- IFF2 in bit 2".format(0x04 if state["iff"] else 0x00),
        "byte(0x{:02x})          -- R".format(state['r']),
        "word(0x{:04x})        -- AF".format(state["af"]),
        "word(0x{:04x})        -- SP".format(stored_sp),
        "byte({})             -- interrupt mode".format(state['im']),
        "byte({})             -- border".format(state['border']),
    ]


def _safe_label(name: str) -> str:
    """Make a ROM routine name usable as a label: ``SA/LD-RET`` -> ``SA_LD_RET``."""
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in name)
    return cleaned if cleaned[:1].isalpha() else "R_{}".format(cleaned)
