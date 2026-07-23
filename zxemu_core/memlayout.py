"""Free-space bookkeeping for placing an asset's bytes somewhere in memory.

Deliberately a **sibling of** ``memory.py``, not a submodule of ``assets/`` -- placement
is a question about the memory model itself ("what's free, what already lives here"),
and the future memory-dumper (turning a running program's RAM back into sources,
tracked in ``DEV_PLAN.md``) needs that same "what lives where" model for the opposite
direction: this module places bytes *into* memory, that feature reads bytes *out*.

**A known, stated limitation, not a hidden gap**: "free" here means "not
hardware-reserved (ROM, the screen) and not already claimed by another placed asset."
It has no idea where the user's own hand-assembled code and data live, because that is
the same undecidable-without-execution problem the memory-dumper backlog item already
grapples with -- the same bytes can be a valid instruction stream and valid pixel data,
so nothing short of actually running the program can say for certain "this address is
code." Auto-locate can therefore suggest a spot that collides with hand-written `ORG`'d
code; the UI must say so rather than imply certainty it doesn't have. A real fix would
extend the build's SLD reading (``zxemu_ui.workspace.sld``) to also capture the `page`
column it currently ignores, and treat every address the last build actually emitted as
occupied too.
"""

from __future__ import annotations

from zxemu_core.memory import BANK_SIZE, SCREEN_BYTES

Range = tuple[int, int]  # (start_offset, length), both in bytes within one bank


def bank_ids_for_model(model: str) -> list[str]:
    """The addressable banks for a machine model, in a stable, model-appropriate order.

    48K's RAM is wired statically to slots, never independently swapped, so its banks
    are named by the slot they occupy (``ram1``/``ram2``/``ram3``) rather than an
    arbitrary bank number -- there's no other bank a 48K's "ram1" could ever mean. 128K
    has a real, independently-pageable bank pool, so its names are the actual bank
    numbers (``ram0``..``ram7``) rather than whichever slot they happen to sit in *now*.
    """
    if model == "128k":
        return ["rom0", "rom1"] + [f"ram{n}" for n in range(8)]
    return ["rom", "ram1", "ram2", "ram3"]


def _screen_bank_ids(model: str) -> set[str]:
    """Which bank(s) hold display memory -- the normal screen, and on 128K the shadow screen too."""
    return {"ram5", "ram7"} if model == "128k" else {"ram1"}


def _hardware_reserved(bank_id: str, model: str) -> list[Range]:
    """Ranges within ``bank_id`` no asset may ever claim, before any asset is placed."""
    if bank_id.startswith("rom"):
        return [(0, BANK_SIZE)]
    if bank_id in _screen_bank_ids(model):
        return [(0, SCREEN_BYTES)]
    return []


class FreeSpaceIndex:
    """Tracks placed ranges per bank and finds room for new ones.

    Seeded with the hardware-reserved ranges for the given model, so ROM and the
    screen's bytes are unavailable from the start -- callers never need to remember to
    exclude them by hand.
    """

    def __init__(self, model: str):
        self.model = model
        self._bank_ids = bank_ids_for_model(model)
        self._placed: dict[str, list[Range]] = {bank_id: [] for bank_id in self._bank_ids}
        for bank_id in self._bank_ids:
            self._placed[bank_id].extend(_hardware_reserved(bank_id, model))

    def place(self, bank: str, offset: int, length: int) -> None:
        if bank not in self._placed:
            raise ValueError(f"unknown bank {bank!r} for model {self.model!r}")
        if length <= 0:
            raise ValueError(f"length must be positive, got {length}")
        if offset < 0 or offset + length > BANK_SIZE:
            raise ValueError(f"{bank}:{offset}+{length} doesn't fit in a {BANK_SIZE}-byte bank")
        for start, existing_length in self._placed[bank]:
            if offset < start + existing_length and start < offset + length:
                raise ValueError(
                    f"{bank}:{offset}+{length} overlaps an existing range at {bank}:{start}+{existing_length}"
                )
        self._placed[bank].append((offset, length))

    def free_ranges(self, bank: str) -> list[Range]:
        if bank not in self._placed:
            raise ValueError(f"unknown bank {bank!r} for model {self.model!r}")
        occupied = sorted(self._placed[bank])
        free: list[Range] = []
        cursor = 0
        for start, length in occupied:
            if start > cursor:
                free.append((cursor, start - cursor))
            cursor = max(cursor, start + length)
        if cursor < BANK_SIZE:
            free.append((cursor, BANK_SIZE - cursor))
        return free

    def _default_search_order(self) -> list[str]:
        """RAM before ROM (never ROM, in fact); non-screen RAM before screen-bank leftovers."""
        screen_banks = _screen_bank_ids(self.model)
        ram_banks = [b for b in self._bank_ids if not b.startswith("rom")]
        return [b for b in ram_banks if b not in screen_banks] + [b for b in ram_banks if b in screen_banks]

    def auto_locate(self, length: int, prefer_banks: list[str] | None = None) -> tuple[str, int] | None:
        """First-fit: the first free range big enough, searching ``prefer_banks`` in order.

        Defaults to non-screen RAM first, then the screen bank's leftover space, and
        never ROM. Places the asset immediately on success (so a second call doesn't
        offer the same space twice) and returns ``(bank, offset)``, or ``None`` if
        nothing free is big enough anywhere.
        """
        for bank in prefer_banks or self._default_search_order():
            for start, free_length in self.free_ranges(bank):
                if free_length >= length:
                    self.place(bank, start, length)
                    return bank, start
        return None
