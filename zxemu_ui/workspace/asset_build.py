"""Turning a project's manifest assets into bytes on disk, and into an ``.asm`` include.

The cache convention here (``<project>/.zxide/generated/<symbol>.bin``) is the one
thing both the memory-map's Design mode and the real build regenerator agree on: the
memory map needs to know an asset's *byte length* to draw its placement rectangle
before a build has ever run, and the build needs the exact same bytes to ``incbin``.
Rather than convert twice (and risk the two disagreeing), both read/write this one
cache, keyed by the asset's symbol.

``regenerate_assets_asm`` is the whole pipeline: resolve any ``"auto"`` placements,
run each asset's converter, cache the bytes, then emit ``assets_generated.asm`` -- one
``ORG``/label/``incbin`` block per asset, plus ``equ`` constants so hand-written code
can address a frame/glyph/tile without hardcoding a number that would go stale on
re-import. On a 128K machine, placing bytes into a specific physical bank regardless of
runtime paging uses sjasmplus's ``SLOT``/``PAGE`` pseudo-ops (verified against the real
tool: ``SLOT 1`` / ``PAGE 7`` / ``ORG $4000`` really does land bytes in RAM bank 7, even
though bank 7 is never mapped into slot 1 at runtime -- these directives are purely
about *where in the assembled snapshot* the bytes go, independent of the hardware
paging they'll later be viewed through).
"""

from __future__ import annotations

import json
from pathlib import Path

from zxemu_core.assets.manifest import AssetEntry, AssetKind, FrameSequence
from zxemu_core.assets.registry import convert_asset
from zxemu_core.assets.tilemap_convert import parse_tilemap_json
from zxemu_core.memlayout import FreeSpaceIndex, bank_ids_for_model
from zxemu_core.memory import BANK_SIZE
from zxemu_ui.workspace import sld

GENERATED_SUBDIR = Path(".zxide") / "generated"
GENERATED_ASM_NAME = "assets_generated.asm"
ASSETS_INCLUDE_LINE = 'include "assets_generated.asm"'

# Used to size a placement rectangle before an asset has ever been converted (e.g.
# right after a drag-drop, before the first build) -- honest about being a guess, not a
# real measurement, so Design mode still shows *something* rather than nothing.
PLACEHOLDER_LENGTH = 32

# Real hardware slot each bank is wired to when addressed for assembly purposes: ROM in
# slot 0, RAM2/RAM5 fixed to their usual slots, everything else via the one "free
# choice" slot (3) -- matches the actual Spectrum 128K memory map, even though SLOT/PAGE
# would technically accept any combination (see module docstring).
_SLOT_BASE = (0x0000, 0x4000, 0x8000, 0xC000)


# Which SLD slots reliably identify a fixed bank, per model -- see sld.py's docstring
# for why slot 3 on 128K is deliberately excluded (it can hold any of 8 banks depending
# on runtime paging the SLD has no way to see; slots 0-3 on 48K and slots 1/2 on 128K
# never repage, so code seen there is unambiguously in that one bank).
_SAFE_SLOT_BANKS = {
    "48k": dict(enumerate(bank_ids_for_model("48k"))),
    "128k": {1: "ram5", 2: "ram2"},
}

# When two traced instruction-start addresses are close together, treat everything
# between them as occupied too (a multi-byte instruction's own operand bytes, or a
# small data table, would otherwise show as "free" gaps between two single-byte
# marks). Beyond this gap, assume it's a genuine break (a different ORG region) rather
# than bridging two unrelated blocks into one falsely-huge reserved range.
_MAX_CODE_GAP = 32
_LAST_INSTRUCTION_SPAN = 4  # the longest real Z80 instruction is 4 bytes


def _coalesce_addresses(addresses: set[int]) -> list[tuple[int, int]]:
    """Merge nearby trace addresses into (offset, length) ranges, within one bank."""
    ordered = sorted(addresses)
    ranges: list[tuple[int, int]] = []
    start = prev = ordered[0]
    for addr in ordered[1:]:
        if addr - prev <= _MAX_CODE_GAP:
            prev = addr
            continue
        ranges.append((start, prev - start + _LAST_INSTRUCTION_SPAN))
        start = prev = addr
    ranges.append((start, prev - start + _LAST_INSTRUCTION_SPAN))
    return ranges


def _sld_path(project) -> Path:
    build_config = project.load_manifest().get("build", {})
    output = project.folder / build_config.get("output", "main.sna")
    return output.with_suffix(".sld")


def reserved_code_ranges(project) -> dict[str, list[tuple[int, int]]]:
    """Bank -> occupied (offset, length) ranges, from the *previous* build's SLD, if any.

    There is no way to know where hand-written code will land before a first build
    ever runs (the same undecidable-without-execution problem the memory-dumper
    backlog item already names) -- so this is deliberately a converges-over-builds
    mitigation, not a one-shot fix: the first build after adding an asset can still
    collide, but every build after that knows what the previous one actually placed
    where, for the banks that reliably mean the same physical RAM every time.
    """
    path = _sld_path(project)
    if not path.exists():
        return {}
    source_map = sld.parse(path.read_text(encoding="utf-8"), base_dir=project.folder)
    safe_banks = _SAFE_SLOT_BANKS.get(project.model, {})

    ranges: dict[str, list[tuple[int, int]]] = {}
    for slot, addresses in source_map.addresses_by_slot.items():
        bank = safe_banks.get(slot)
        if bank is None or not addresses:
            continue
        offsets = {addr % BANK_SIZE for addr in addresses}
        ranges[bank] = _coalesce_addresses(offsets)
    return ranges


class AssetBuildError(ValueError):
    """An asset couldn't be converted or placed -- meant to become a build-log error, not a crash."""


def cache_path(project, symbol: str) -> Path:
    return project.folder / GENERATED_SUBDIR / f"{symbol}.bin"


def cached_length(project, entry) -> int | None:
    """The real converted byte length, if this asset has been converted at least once."""
    path = cache_path(project, entry.symbol)
    return path.stat().st_size if path.exists() else None


def display_length(project, entry) -> tuple[int, bool]:
    """``(length, is_placeholder)`` -- the best byte-length estimate available right now."""
    length = cached_length(project, entry)
    if length is not None:
        return length, False
    return PLACEHOLDER_LENGTH, True


def resolve_auto_placements(project) -> None:
    """Place every ``"auto"`` asset into the first free space that fits it.

    Shared by the memory map's "Auto-locate" button and every build, so a project
    always builds even if you forgot to click the button -- the button is a way to
    *see* where things land before building, not the only way they get placed.

    Also avoids the previous build's known hand-written-code addresses (see
    ``reserved_code_ranges``) -- best-effort and slot-limited, but it directly closes
    the collision this project hit twice in practice: a freshly imported asset's
    auto-located "first free byte" landing exactly on a template's own ``org $8000``.
    """
    assets = project.assets()
    index = FreeSpaceIndex(project.model)
    for bank, ranges in reserved_code_ranges(project).items():
        for offset, length in ranges:
            try:
                index.place(bank, offset, length)
            except ValueError:
                pass  # already covered by a hardware-reserved range (e.g. abuts the screen)
    for entry in assets:
        if isinstance(entry.placement, dict):
            length, _placeholder = display_length(project, entry)
            try:
                index.place(entry.placement["bank"], entry.placement["offset"], length)
            except ValueError:
                pass  # a stale/out-of-range placement shouldn't block locating the rest
    for entry in assets:
        if entry.placement != "auto":
            continue
        length, _placeholder = display_length(project, entry)
        location = index.auto_locate(length)
        if location is not None:
            bank, offset = location
            project.set_asset_placement(entry.id, bank, offset)


def auto_locate_one(project, asset_id: str) -> bool:
    """Place a single asset via first-fit auto-locate, without disturbing other ``"auto"`` entries.

    Used by the Inspector's per-asset "Auto-locate this asset" action -- unlike
    ``resolve_auto_placements`` (every pending asset, at once), this touches only the
    one asset you're looking at. Returns whether a spot was found.
    """
    assets = project.assets()
    target = next((entry for entry in assets if entry.id == asset_id), None)
    if target is None:
        raise ValueError(f"no asset with id {asset_id!r}")

    index = FreeSpaceIndex(project.model)
    for entry in assets:
        if entry.id != asset_id and isinstance(entry.placement, dict):
            length, _placeholder = display_length(project, entry)
            try:
                index.place(entry.placement["bank"], entry.placement["offset"], length)
            except ValueError:
                pass

    length, _placeholder = display_length(project, target)
    location = index.auto_locate(length)
    if location is None:
        return False
    bank, offset = location
    project.set_asset_placement(asset_id, bank, offset)
    return True


def ensure_assets_include(project) -> None:
    """Make sure the project's main file ``include``s the generated asset asm, once.

    New templates bake this in from the start; existing projects get it appended the
    first time this runs (idempotent -- checked by literal presence, so it is safe to
    call on every build).
    """
    main_path = project.folder / project.load_manifest().get("main", "main.asm")
    if not main_path.exists():
        return
    text = main_path.read_text(encoding="utf-8")
    if ASSETS_INCLUDE_LINE in text:
        return
    lines = text.splitlines()
    insert_at = 0
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped.startswith("include") or stripped.startswith("device"):
            insert_at = i + 1
    lines.insert(insert_at, f"    {ASSETS_INCLUDE_LINE}")
    main_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _slot_for_bank(bank_id: str) -> int:
    if bank_id.startswith("rom"):
        return 0
    if bank_id == "ram5":
        return 1
    if bank_id == "ram2":
        return 2
    return 3


def _address_lines(model: str, bank: str, offset: int) -> list[str]:
    if model != "128k":
        slot = bank_ids_for_model("48k").index(bank)
        return [f"    org ${_SLOT_BASE[slot] + offset:04x}"]
    bank_number = int(bank[3:])  # "ram3" -> 3, "rom1" -> 1 -- both prefixes are 3 characters
    return [
        f"    SLOT {_slot_for_bank(bank)}",
        f"    PAGE {bank_number}",
        f"    org ${_SLOT_BASE[_slot_for_bank(bank)] + offset:04x}",
    ]


def _asset_asm_block(project, entry: AssetEntry, raw_bytes: bytes, result, cache_rel_path: str) -> list[str]:
    bank, offset = entry.placement["bank"], entry.placement["offset"]
    lines = [f"; {entry.symbol} ({entry.kind.value}) -- {bank}:{offset:#06x}, {len(raw_bytes)} bytes"]
    lines += _address_lines(project.model, bank, offset)
    lines.append(f"{entry.symbol}:")
    lines.append(f'    incbin "{cache_rel_path}"')
    lines.append(f"{entry.symbol}_LENGTH: equ {len(raw_bytes)}")

    if isinstance(result, FrameSequence):
        lines.append(f"{entry.symbol}_FRAME_COUNT: equ {result.frame_count}")
        lines.append(f"{entry.symbol}_FRAME_STRIDE: equ {result.frame_stride}")
        if entry.kind is AssetKind.FONT:
            first_char = entry.params.get("first_char_code", 32)
            lines.append(f"{entry.symbol}_FIRST_CHAR: equ {first_char}")
        if result.has_attrs:
            # Where the attribute plane starts within each frame's stride -- after the
            # pixel plane, and the mask plane too if this sprite also has one.
            attr_offset = result.plane_bytes * (2 if result.has_mask else 1)
            lines.append(f"{entry.symbol}_ATTR_OFFSET: equ {attr_offset}")
    elif entry.kind is AssetKind.TILEMAP:
        tilemap = parse_tilemap_json(json.loads((project.folder / entry.source).read_text()))
        lines.append(f"{entry.symbol}_WIDTH: equ {tilemap.width}")
        lines.append(f"{entry.symbol}_HEIGHT: equ {tilemap.height}")
        lines.append(f"; tileset: {tilemap.tileset_symbol}")

    lines.append("")
    return lines


def regenerate_assets_asm(project) -> Path:
    """Convert every manifest asset, cache its bytes, and emit ``assets_generated.asm``.

    Runs tileset-producing kinds (``sprite_sheet``/``sprite_sequence``/``font``)
    before ``tilemap`` entries, since a tilemap's conversion needs to validate its tile
    indices against the tileset's real frame count.
    """
    ensure_assets_include(project)
    resolve_auto_placements(project)
    assets = project.assets()

    def read_bytes(rel_path: str) -> bytes:
        return (project.folder / rel_path).read_bytes()

    frame_counts: dict[str, int] = {}  # symbol -> frame_count, for tilemap lookups
    converted: dict[str, object] = {}  # asset id -> bytes or FrameSequence
    warnings: list[str] = []

    non_tilemap = [e for e in assets if e.kind is not AssetKind.TILEMAP]
    tilemaps = [e for e in assets if e.kind is AssetKind.TILEMAP]

    for entry in non_tilemap:
        try:
            entry_warnings: list[str] = []
            result = convert_asset(entry, read_bytes=read_bytes, warnings=entry_warnings)
        except Exception as exc:
            raise AssetBuildError(f"asset '{entry.symbol}': {exc}") from exc
        warnings.extend(f"{entry.symbol}: {w}" for w in entry_warnings)
        converted[entry.id] = result
        if isinstance(result, FrameSequence):
            frame_counts[entry.symbol] = result.frame_count

    def tileset_frame_count(symbol: str) -> int:
        if symbol not in frame_counts:
            raise AssetBuildError(f"tilemap references unknown tileset symbol '{symbol}'")
        return frame_counts[symbol]

    for entry in tilemaps:
        try:
            result = convert_asset(entry, read_bytes=read_bytes, tileset_frame_count=tileset_frame_count)
        except Exception as exc:
            raise AssetBuildError(f"asset '{entry.symbol}': {exc}") from exc
        converted[entry.id] = result

    lines = [
        f"; {GENERATED_ASM_NAME} -- GENERATED FILE, do not edit by hand.",
        "; Regenerated on every build from this project's imported assets (see zxide.json).",
        "",
    ]
    for entry in assets:
        if not isinstance(entry.placement, dict):
            raise AssetBuildError(f"asset '{entry.symbol}' has no placement (auto-locate found no free space)")
        result = converted[entry.id]
        raw_bytes = result.data if isinstance(result, FrameSequence) else result

        cache_file = cache_path(project, entry.symbol)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(raw_bytes)
        cache_rel_path = cache_file.relative_to(project.folder).as_posix()

        lines.extend(_asset_asm_block(project, entry, raw_bytes, result, cache_rel_path))

    output_path = project.folder / GENERATED_ASM_NAME
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
