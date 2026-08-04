"""The whole project's memory plan: what claims which bytes, and what collides.

One level up from :mod:`zxemu_core.debug.asm_layout`, which reads a single source tree.
This module answers the same question for a *project*: it scans from the manifest's main
file through its includes, adds the placed assets the manifest records, folds in whatever
the last build's ``.sld`` proved, and reports the overlaps.

Three sources of truth, ranked by how much they can promise, which is the ordering the
whole debug package works by:

1. **The ``.sld`` from the last build** -- what the assembler actually emitted. Exact, but
   only for banks a slot reliably identifies (see ``sld.py``), and only after a build.
2. **The source scan** -- where the ``org``s say bytes go. Available while you type, and
   honest about macros and conditionals it cannot expand (``Region.estimated``).
3. **The manifest's asset placements** -- exact once an asset has been converted at least
   once, a placeholder length before that.

They are combined rather than ranked winner-takes-all: for *drawing*, the scan wins because
it carries the names; for *avoiding a collision*, the union of all three wins, because a
byte either source claims is a byte auto-locate must not hand out twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from zxemu_core.debug import asm_layout
from zxemu_core.debug.asm_layout import Region
from zxemu_core.memlayout import SLOT_BASE, slot_for_bank
from zxemu_core.memory import BANK_SIZE
from zxemu_ui.workspace import asset_build
from zxemu_ui.workspace.project import snapshot_from_source


@dataclass
class Conflict:
    """Two claims on the same bytes, named so the message can say what hit what."""

    bank: str
    offset: int
    length: int          # how many bytes actually overlap
    first: str
    second: str

    def describe(self) -> str:
        return "{}:${:04x} -- {} overlaps {} for {} bytes".format(self.bank, self.offset, self.first, self.second, self.length)


@dataclass
class MemoryPlan:
    """Everything known about where this project's bytes live."""

    regions: list[Region] = field(default_factory=list)   # from the source scan (code/data)
    assets: list[Region] = field(default_factory=list)    # from the manifest, kind="asset"
    conflicts: list[Conflict] = field(default_factory=list)
    missing_includes: list[str] = field(default_factory=list)
    bad_annotations: list[str] = field(default_factory=list)  # `; zxide:` lines that made no sense
    missing_binaries: list[str] = field(default_factory=list)  # `incbin`s whose file is not there
    built: bool = False                                   # whether an .sld was available
    # Which source this plan is a plan *of*. A project has more than one program in it --
    # the game, and a test that exercises one part of it -- and they have different memory
    # maps, so a plan that doesn't say which one you are looking at is ambiguous.
    entries: list[str] = field(default_factory=list)

    @property
    def claims(self) -> list[Region]:
        """Every claim on memory, whatever produced it."""
        return self.regions + self.assets

    def occupied(self) -> dict[str, list[tuple[int, int]]]:
        """Bank -> ``(offset, length)`` ranges that are spoken for, for the free-space search.

        Ambiguous-bank regions are left out: a 128K ``org $c000`` with no ``PAGE`` could be
        in any of eight banks, and reserving the same offset in all of them would make a
        third of RAM unusable on the strength of a guess.
        """
        ranges: dict[str, list[tuple[int, int]]] = {}
        for claim in self.claims:
            if not claim.bank or claim.claimed <= 0:
                continue
            ranges.setdefault(claim.bank, []).append((claim.offset, claim.claimed))
        return ranges


def entry_points(project, main=None) -> list[str]:
    """The sources to scan from, most-trusted first.

    Three answers, in the order they deserve to be believed: the one the caller names (in
    practice the file the editor has open, which is what F5 would assemble), then the
    manifest's ``main``, then -- for a folder zxide did not scaffold, where neither is
    right -- whatever at the root actually looks buildable. "Buildable" means it carries a
    ``savesna``, the same test ``builder`` already applies to find the snapshot a build
    wrote, so this agrees with what the assembler is being asked to do rather than guessing
    from filenames. A real project hit exactly this: a manifest still saying ``main.asm``
    beside a source tree whose entry point had been renamed.

    The caller's file has to pass that same buildable test, and this is the one place that
    decides it. A project holds two kinds of ``.asm``: the few you can point an assembler
    at, and the many that only make sense ``include``d by one of them. Scanning an include
    on its own would draw a plan of one file -- technically true, and a lie about the
    project, since every block the rest of the tree places would simply be absent. So a
    focused ``tests/sound_test.asm`` moves the whole plan onto that program (which is the
    point: it is a different program, with its own memory map), while a focused
    ``core/audio/music.asm`` leaves the plan showing whatever the project last had.
    """
    candidates = [main if main and snapshot_from_source(project.folder / main) else None,
                  project.load_manifest().get("main", "main.asm")]
    for candidate in candidates:
        if candidate and (project.folder / candidate).is_file():
            return [candidate]
    return sorted(path.name for path in project.folder.glob("*.asm") if snapshot_from_source(path))


def build_plan(project, read_source=None, main=None) -> MemoryPlan:
    """Scan the project and return its plan.

    ``read_source`` maps a path to its text; the editor passes one that prefers an open,
    unsaved tab, which is what makes Refresh show the ``org`` you just typed rather than
    the one you last saved. ``main`` names the source to scan from; :func:`entry_points`
    says what happens when it is absent or no longer exists.
    """
    reader = read_source if read_source is not None else _disk_reader
    plan = MemoryPlan()

    for entry in entry_points(project, main):
        text = reader(str(project.folder / entry))
        if text is None:
            continue
        plan.entries.append(entry)
        result = asm_layout.scan(
            text, project.model, origin=entry, base_dir=project.folder,
            read_source=reader, file_size=_disk_size,
        )
        # The generated asset include is skipped: every block in it is one of the manifest
        # assets added below, so keeping both would double-count the same bytes and -- worse --
        # report each asset as overlapping itself.
        plan.regions.extend(region for region in result.regions if region.origin != asset_build.GENERATED_ASM_NAME)
        plan.missing_includes.extend(result.missing_includes)
        plan.bad_annotations.extend(result.bad_annotations)
        plan.missing_binaries.extend(result.missing_binaries)
    plan.assets = _asset_regions(project)

    sld_ranges = asset_build.reserved_code_ranges(project)
    plan.built = bool(sld_ranges)
    _apply_sld(plan.regions, sld_ranges)

    plan.conflicts = _conflicts(plan.claims)
    return plan


def _asset_regions(project) -> list[Region]:
    """Placed assets as regions, so one overlap check covers code, data and assets alike."""
    regions: list[Region] = []
    for entry in project.assets():
        if not isinstance(entry.placement, dict):
            continue  # still "auto" -- it has no claim on anything yet
        bank, offset = entry.placement.get("bank", ""), entry.placement.get("offset", 0)
        if not bank:
            continue
        length, placeholder = asset_build.display_length(project, entry)
        slot = slot_for_bank(bank, project.model)
        source = entry.source if isinstance(entry.source, str) else ""
        regions.append(
            Region(
                name=entry.symbol, kind="asset", slot=slot, bank=bank, offset=offset, length=length,
                address=SLOT_BASE[slot] + offset, origin=source, estimated=placeholder,
            )
        )
    return regions


def _apply_sld(regions: list[Region], sld_ranges: dict[str, list[tuple[int, int]]]) -> None:
    """Replace a scanned region's guessed length with what the last build really emitted.

    Only where the build agrees the region exists: an SLD range starting at exactly the
    region's offset is that ``org`` confirmed, and the bytes it traced past that point are
    the region's real extent. Anything less certain is left alone rather than "corrected"
    towards a number that might belong to the next region along -- and the extension is
    clamped to the following region in the same bank for the same reason.
    """
    for bank, ranges in sld_ranges.items():
        in_bank = sorted([region for region in regions if region.bank == bank], key=lambda region: region.offset)
        for index, region in enumerate(in_bank):
            limit = in_bank[index + 1].offset if index + 1 < len(in_bank) else BANK_SIZE
            confirmed = [(start, length) for start, length in ranges if start == region.offset]
            if not confirmed:
                continue
            reach = max(start + length for start, length in ranges if region.offset <= start < limit)
            region.length = min(max(region.length, reach - region.offset), limit - region.offset)
            region.estimated = False


def _conflicts(claims: list[Region]) -> list[Conflict]:
    """Every overlapping pair, in address order. O(n log n) via a sort, not a full cross-product."""
    found: list[Conflict] = []
    ordered = sorted([claim for claim in claims if claim.bank and claim.claimed > 0], key=lambda claim: (claim.bank, claim.offset))
    for index, claim in enumerate(ordered):
        for other in ordered[index + 1:]:
            if other.bank != claim.bank or other.offset >= claim.end:
                break  # sorted by offset, so nothing further along can overlap either
            overlap = min(claim.end, other.end) - other.offset
            found.append(Conflict(bank=claim.bank, offset=other.offset, length=overlap, first=claim.name, second=other.name))
    return found


def _disk_reader(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _disk_size(path: str) -> int | None:
    try:
        return Path(path).stat().st_size
    except OSError:
        return None
