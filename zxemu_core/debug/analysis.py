"""Static and runtime analysis of what's in memory: search, coverage, cross-references.

The debugger's other panels answer "what is the machine doing *now*". These answer
questions about the program as a whole -- the reverse-engineering half of the job:

    search      where do these bytes / this text appear?
    coverage    which addresses has the CPU actually executed?
    xrefs       what calls or jumps to this address? what reads or writes it?

Two of these are static (a scan of memory as it stands) and one is a recording, and
the difference matters. A static scan is instant and complete but can be fooled --
data that happens to look like a CALL is indistinguishable from a real one, exactly as
in the call-stack inference. Coverage is the opposite: it never lies about what ran,
but only knows what has run *so far*, so an empty result means "not yet", never "never".

Used together they cover each other's weakness: cross-references propose where control
might flow, coverage confirms which of those paths the program actually took.
"""

from __future__ import annotations

from typing import NamedTuple

# Instructions that name a 16-bit address in their two following bytes. These are what
# a cross-reference scan looks for; everything else either has no address operand or
# computes it at runtime (JP (HL) and friends), which no static scan can follow.
_CALL_OPCODES = frozenset({0xCD, 0xC4, 0xCC, 0xD4, 0xDC, 0xE4, 0xEC, 0xF4, 0xFC})
_JUMP_OPCODES = frozenset({0xC3, 0xC2, 0xCA, 0xD2, 0xDA, 0xE2, 0xEA, 0xF2, 0xFA})
_LOAD_FROM = frozenset({0x3A, 0x2A})  # LD A,(nn) / LD HL,(nn)
_LOAD_TO = frozenset({0x32, 0x22})    # LD (nn),A / LD (nn),HL

# Immediate 16-bit loads: LD BC/DE/HL/SP,nn. On a Z80 this is *the* usual way to refer
# to an address -- you load a pointer and work through it -- so leaving these out makes
# a cross-reference search miss most real references. They are reported as "load"
# rather than read/write because that is all we can honestly say: the code took the
# address, and what it does with it is beyond a static scan.
#
# The cost is false positives, since the same opcodes load ordinary numbers too
# (`ld bc,6143` is a count, not a pointer). That is why they get their own label.
_LOAD_IMMEDIATE = frozenset({0x01, 0x11, 0x21, 0x31})

ADDRESS_SPACE = 0x10000


class Reference(NamedTuple):
    """One place that refers to an address, and how."""

    address: int   # where the referring instruction is
    kind: str      # "call" / "jump" / "read" / "write"


def search_bytes(memory, pattern: bytes, start: int = 0, end: int = ADDRESS_SPACE) -> list[int]:
    """Every address in [start, end) where ``pattern`` appears. Empty pattern finds nothing."""
    if not pattern:
        return []
    hits = []
    limit = min(end, ADDRESS_SPACE) - len(pattern)
    first = pattern[0]
    for address in range(max(0, start), limit + 1):
        if memory.read_byte(address) != first:
            continue  # cheap rejection before the full compare
        if all(memory.read_byte(address + i) == b for i, b in enumerate(pattern)):
            hits.append(address)
    return hits


def search_text(memory, text: str, **kwargs) -> list[int]:
    """Search for ASCII text. Spectrum strings are plain ASCII in the printable range."""
    return search_bytes(memory, text.encode("ascii", "ignore"), **kwargs)


def cross_references(memory, target: int, start: int = 0, end: int = ADDRESS_SPACE) -> list[Reference]:
    """Find instructions that call, jump to, read, write, or load ``target``.

    A *static* scan: it walks memory byte by byte looking for three-byte instructions
    whose operand equals the target, without following control flow. That means it sees
    references inside code that never runs, and can be fooled by data whose bytes
    happen to match -- the same 1-in-65536 coincidence the call-stack inference relies
    on being rare. Cross-check anything surprising against the coverage map.

    It cannot see computed destinations (``JP (HL)``, jump tables, self-modified
    operands) at all. Those are invisible to any static scan, and are exactly where a
    trace or coverage map earns its keep.
    """
    target &= 0xFFFF
    low, high = target & 0xFF, (target >> 8) & 0xFF
    found = []
    for address in range(max(0, start), min(end, ADDRESS_SPACE) - 2):
        if memory.read_byte(address + 1) != low or memory.read_byte(address + 2) != high:
            continue
        opcode = memory.read_byte(address)
        if opcode in _CALL_OPCODES:
            found.append(Reference(address, "call"))
        elif opcode in _JUMP_OPCODES:
            found.append(Reference(address, "jump"))
        elif opcode in _LOAD_FROM:
            found.append(Reference(address, "read"))
        elif opcode in _LOAD_TO:
            found.append(Reference(address, "write"))
        elif opcode in _LOAD_IMMEDIATE:
            found.append(Reference(address, "load"))
    return found


#: The window a 128K/Pentagon pages banks through. Below it the mapping never moves --
#: slot 1 is always RAM5 and slot 2 always RAM2 -- so a plain address identifies the bank
#: unambiguously. Above it, the same address may belong to any of eight banks.
PAGED_BASE = 0xC000
PAGED_SIZE = ADDRESS_SPACE - PAGED_BASE


class CoverageMap:
    """Records which addresses the CPU has executed.

    A bytearray flag per address rather than a set: coverage is marked once per
    instruction, so this is on the debug loop's hot path, and ``bytearray`` indexing is
    markedly cheaper than set insertion. 64K of flags is a rounding error next to the
    machine it is watching.

    What it is good for is the question static analysis cannot answer -- "is this code
    dead, or have I just not exercised it?" -- and the honest reading of an unmarked
    address is "not yet", never "never".

    Which bank was it, though?
    -------------------------
    A flat address is a complete answer on a 48K, and on a 128K it is a complete answer
    for everything below :data:`PAGED_BASE` -- slots 1 and 2 hold RAM5 and RAM2 and never
    move. Above it the address alone is ambiguous: eight banks take turns at 0xC000, and
    "0xC123 executed" does not say which one was there.

    That ambiguity **cannot be resolved afterwards**. It is tempting to think the banks
    could be compared against each other to work out which was running, but the
    information was never recorded and is not latent in the bytes: two banks may hold
    identical data, a bank may be modified after its code ran, and a program can swap
    banks at the same address hundreds of times a second.

    So it is recorded as it happens. :meth:`select_bank` is called when the machine pages
    -- from ``Machine128.set_paging``, which is the one place the mapping changes and is
    reached only on a port write -- and marking above 0xC000 then lands in that bank's own
    flags as well as the flat map. Exact, rather than inferred.

    The cost is one branch per instruction on a loop that is already the slow path
    (recording coverage forces per-instruction stepping in the first place), and a 48K
    session allocates no bank arrays at all: ``_paged_target`` stays None and the branch
    falls straight through.
    """

    def __init__(self):
        self.executed = bytearray(ADDRESS_SPACE)
        self.enabled = False
        #: Per-bank flags for the paged window, created only when a bank is selected.
        self.bank_executed: dict[int, bytearray] = {}
        self.current_bank: int | None = None
        self._paged_target: bytearray | None = None

    def clear(self) -> None:
        self.executed = bytearray(ADDRESS_SPACE)
        self.bank_executed = {}
        self._paged_target = None
        if self.current_bank is not None:
            self.select_bank(self.current_bank)   # keep following the live mapping

    def select_bank(self, bank: int) -> None:
        """Follow the machine's paging: subsequent marks above 0xC000 belong to ``bank``.

        Swapping the target array rather than testing a flag on every instruction is the
        same trick used by ``Machine.set_port_watchpoints`` (which swaps the IO hooks) and
        by memory watchpoints (which rebind ``memory.__class__``) -- and for the same
        reason: the check would otherwise sit on a path taken millions of times.
        """
        self.current_bank = bank
        target = self.bank_executed.get(bank)
        if target is None:
            target = bytearray(PAGED_SIZE)
            self.bank_executed[bank] = target
        self._paged_target = target

    def mark(self, address: int) -> None:
        address &= 0xFFFF
        self.executed[address] = 1
        if self._paged_target is not None and address >= PAGED_BASE:
            self._paged_target[address - PAGED_BASE] = 1

    def executed_in_bank(self, bank: int) -> bytearray | None:
        """Flags for one bank's 16K window, or None if that bank never ran anything."""
        return self.bank_executed.get(bank)

    def count(self) -> int:
        return sum(self.executed)

    def ranges(self, minimum_length: int = 1) -> list[tuple[int, int]]:
        """Executed addresses collapsed into (start, end) runs, for a readable summary."""
        runs = []
        start = None
        for address in range(ADDRESS_SPACE):
            if self.executed[address]:
                if start is None:
                    start = address
            elif start is not None:
                if address - start >= minimum_length:
                    runs.append((start, address))
                start = None
        if start is not None and ADDRESS_SPACE - start >= minimum_length:
            runs.append((start, ADDRESS_SPACE))
        return runs
