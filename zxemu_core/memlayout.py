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


#: Models with a real, independently-pageable bank pool behind port 0x7FFD.
#:
#: A Pentagon's address space is a 128K's, bank for bank -- the clone changed the frame
#: timing and bolted on a disk interface, it did not touch the memory map. Everything
#: that reasons about banks therefore treats the two identically, and asks *here* rather
#: than scattering ``model in ("128k", "pentagon")`` through the codebase, where the next
#: clone would have to be added in a dozen places and would be missed in two of them.
PAGED_MODELS = frozenset({"128k", "pentagon"})


def bank_ids_for_model(model: str) -> list[str]:
    """The addressable banks for a machine model, in a stable, model-appropriate order.

    48K's RAM is wired statically to slots, never independently swapped, so its banks
    are named by the slot they occupy (``ram1``/``ram2``/``ram3``) rather than an
    arbitrary bank number -- there's no other bank a 48K's "ram1" could ever mean. 128K
    and Pentagon have a real, independently-pageable bank pool, so their names are the
    actual bank numbers (``ram0``..``ram7``) rather than whichever slot they happen to
    sit in *now*.
    """
    if model in PAGED_MODELS:
        return ["rom0", "rom1"] + ["ram{}".format(n) for n in range(8)]
    return ["rom", "ram1", "ram2", "ram3"]


#: The CPU address each 16K slot starts at. Slots are the *address space*; banks are the
#: memory that can be paged into them, and these four numbers are the only bridge between
#: the two -- which is why they live here rather than in whichever module needed them first.
SLOT_BASE = (0x0000, 0x4000, 0x8000, 0xC000)


def slot_for_address(address: int) -> int:
    """Which of the four 16K slots a CPU address falls in."""
    return (address & 0xFFFF) // BANK_SIZE


def slot_for_bank(bank_id: str, model: str | None = None) -> int:
    """The slot a bank is addressed through when assembling bytes into it.

    On a **paged** machine (the default when no model is given): ROM in slot 0, RAM5 and
    RAM2 fixed to the slots the hardware wires them to, and every other bank through the
    one "free choice" slot 3. sjasmplus's ``SLOT``/``PAGE`` would technically accept any
    combination -- those directives are about where in the assembled image bytes land, not
    about runtime paging -- but matching the real 128K map keeps generated source readable
    as the thing a human would have written.

    On an **unpaged** one the question is simpler and the answer above is wrong: a 48K's
    banks *are* its slots, in order, so ``ram1`` is slot 1 and not the 128K's "anything
    unrecognised goes in slot 3". Pass ``model`` wherever a 48K project can reach this --
    without it, a 48K block at ``$4000`` is reported as living at ``$C000``.
    """
    if model is not None and model not in PAGED_MODELS:
        ids = bank_ids_for_model(model)
        if bank_id in ids:
            return ids.index(bank_id)
    if bank_id.startswith("rom"):
        return 0
    if bank_id == "ram5":
        return 1
    if bank_id == "ram2":
        return 2
    return 3


def default_bank_for_slot(model: str, slot: int) -> str | None:
    """Which bank a slot holds when the source hasn't said -- or None when nothing can be.

    The inverse of :func:`slot_for_bank`, and deliberately partial. On 48K every slot is
    wired to exactly one bank forever, so the answer is always certain. On 128K slots 0-2
    are certain *by convention* (ROM0, RAM5, RAM2 -- what the machine boots with), but slot
    3 can hold any of eight banks depending on a port write this module cannot see, so it
    returns None rather than name one. Callers are expected to say "unknown" too: see
    ``workspace/sld.py``, which excludes the same slot for the same reason.
    """
    if model not in PAGED_MODELS:
        return bank_ids_for_model(model)[slot]
    return {0: "rom0", 1: "ram5", 2: "ram2"}.get(slot)


def _screen_bank_ids(model: str) -> set[str]:
    """Which bank(s) hold display memory -- the normal screen, and the shadow screen too
    on the models that have one."""
    return {"ram5", "ram7"} if model in PAGED_MODELS else {"ram1"}


def hardware_reserved(bank_id: str, model: str) -> list[Range]:
    """Ranges within ``bank_id`` no asset may ever claim, before any asset is placed.

    Public because "what is free here" is asked in two ways: :class:`FreeSpaceIndex`
    answers it while *placing* things, and the memory plan window answers it while
    *drawing* them, where a claim that overlaps another must not make the bytes under it
    look empty. Both have to start from the same reserved ranges.
    """
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
            self._placed[bank_id].extend(hardware_reserved(bank_id, model))

    def place(self, bank: str, offset: int, length: int) -> None:
        if bank not in self._placed:
            raise ValueError("unknown bank {!r} for model {!r}".format(bank, self.model))
        if length <= 0:
            raise ValueError("length must be positive, got {}".format(length))
        if offset < 0 or offset + length > BANK_SIZE:
            raise ValueError("{}:{}+{} doesn't fit in a {}-byte bank".format(bank, offset, length, BANK_SIZE))
        for start, existing_length in self._placed[bank]:
            if offset < start + existing_length and start < offset + length:
                raise ValueError(
                    "{}:{}+{} overlaps an existing range at {}:{}+{}".format(bank, offset, length, bank, start, existing_length)
                )
        self._placed[bank].append((offset, length))

    def free_ranges(self, bank: str) -> list[Range]:
        if bank not in self._placed:
            raise ValueError("unknown bank {!r} for model {!r}".format(bank, self.model))
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
