"""Tests for asset->bytes->asm build integration (zxemu_ui.workspace.asset_build)."""

from __future__ import annotations

import pytest

from tests.unit.bmp_fixtures import write_bmp24
from zxemu_core.assets.manifest import AssetKind
from zxemu_ui.workspace.asset_build import (
    ASSETS_INCLUDE_LINE,
    AssetBuildError,
    _coalesce_addresses,
    _sld_path,
    cache_path,
    display_length,
    ensure_assets_include,
    regenerate_assets_asm,
    reserved_code_ranges,
    resolve_auto_placements,
)
from zxemu_ui.workspace.project import Project


def _project(tmp_path, model="48k"):
    return Project.create(tmp_path / "p", "P", model)


def test_display_length_is_placeholder_before_first_build(tmp_path):
    project = _project(tmp_path)
    entry = project.add_asset("a.bin", AssetKind.BINARY)
    (project.folder / "a.bin").write_bytes(b"\x01\x02\x03")
    length, is_placeholder = display_length(project, entry)
    assert is_placeholder
    assert length > 0


def test_display_length_is_exact_after_caching(tmp_path):
    project = _project(tmp_path)
    entry = project.add_asset("a.bin", AssetKind.BINARY)
    cache_path(project, entry.symbol).parent.mkdir(parents=True, exist_ok=True)
    cache_path(project, entry.symbol).write_bytes(b"\x01\x02\x03\x04")
    length, is_placeholder = display_length(project, entry)
    assert not is_placeholder
    assert length == 4


def test_resolve_auto_placements_fills_in_auto_assets(tmp_path):
    project = _project(tmp_path)
    project.add_asset("a.bin", AssetKind.BINARY)
    resolve_auto_placements(project)
    entry = project.assets()[0]
    assert isinstance(entry.placement, dict)
    assert entry.placement["bank"] in ("ram1", "ram2", "ram3")


def test_resolve_auto_placements_never_overlaps_existing(tmp_path):
    project = _project(tmp_path)
    first = project.add_asset("a.bin", AssetKind.BINARY)
    project.set_asset_placement(first.id, "ram2", 0)
    project.add_asset("b.bin", AssetKind.BINARY)
    resolve_auto_placements(project)
    second = project.assets()[1]
    assert second.placement["bank"] != "ram2" or second.placement["offset"] >= 32


def test_ensure_assets_include_is_idempotent(tmp_path):
    project = _project(tmp_path)
    main_path = project.folder / "main.asm"
    lines = [line for line in main_path.read_text().splitlines() if "assets_generated" not in line]
    main_path.write_text("\n".join(lines) + "\n")
    assert ASSETS_INCLUDE_LINE not in main_path.read_text()

    ensure_assets_include(project)
    ensure_assets_include(project)
    assert main_path.read_text().count(ASSETS_INCLUDE_LINE) == 1


def test_regenerate_assets_asm_emits_org_label_incbin_for_48k(tmp_path):
    project = _project(tmp_path, "48k")
    (project.folder / "sprite.bmp").write_bytes(write_bmp24(8, 8, lambda x, y: (0, 0, 0)))
    entry = project.add_asset(
        "sprite.bmp",
        AssetKind.SPRITE_SHEET,
        symbol="sprite",
        params={"frame_width": 8, "frame_height": 8, "layout": {"grid": {"cols": 1, "rows": 1}}},
    )
    project.set_asset_placement(entry.id, "ram2", 100)

    output_path = regenerate_assets_asm(project)
    text = output_path.read_text()
    assert "org $8064" in text  # slot2 base 0x8000 + offset 100
    assert "sprite:" in text
    assert 'incbin ".zxide/generated/sprite.bin"' in text
    assert "sprite_FRAME_COUNT: equ 1" in text
    assert cache_path(project, "sprite").read_bytes() == bytes([0xFF] * 8)


def test_regenerate_assets_asm_emits_slot_page_for_128k(tmp_path):
    project = _project(tmp_path, "128k")
    (project.folder / "sprite.bmp").write_bytes(write_bmp24(8, 8, lambda x, y: (0, 0, 0)))
    entry = project.add_asset(
        "sprite.bmp",
        AssetKind.SPRITE_SHEET,
        symbol="sprite",
        params={"frame_width": 8, "frame_height": 8, "layout": {"grid": {"cols": 1, "rows": 1}}},
    )
    project.set_asset_placement(entry.id, "ram3", 200)

    text = regenerate_assets_asm(project).read_text()
    assert "SLOT 3" in text
    assert "PAGE 3" in text
    assert "org $c0c8" in text  # slot3 base 0xc000 + offset 200 (0xc8)


def test_regenerate_assets_asm_raises_asset_build_error_on_bad_conversion(tmp_path):
    project = _project(tmp_path)
    (project.folder / "bad.pt3").write_bytes(b"NOTPT3")
    entry = project.add_asset("bad.pt3", AssetKind.PT3)
    project.set_asset_placement(entry.id, "ram2", 0)
    with pytest.raises(AssetBuildError, match="bad"):
        regenerate_assets_asm(project)


def test_regenerate_assets_asm_font_emits_first_char_equ(tmp_path):
    project = _project(tmp_path)
    (project.folder / "font.bmp").write_bytes(write_bmp24(16, 8, lambda x, y: (0, 0, 0)))
    entry = project.add_asset("font.bmp", AssetKind.FONT, symbol="font", params={"first_char_code": 32})
    project.set_asset_placement(entry.id, "ram2", 0)
    text = regenerate_assets_asm(project).read_text()
    assert "font_FIRST_CHAR: equ 32" in text


def test_regenerate_assets_asm_tilemap_after_tileset(tmp_path):
    import json

    project = _project(tmp_path)
    (project.folder / "tiles.bmp").write_bytes(write_bmp24(16, 8, lambda x, y: (0, 0, 0)))
    tileset = project.add_asset(
        "tiles.bmp",
        AssetKind.SPRITE_SHEET,
        symbol="tileset",
        params={"frame_width": 8, "frame_height": 8, "layout": {"grid": {"cols": 2, "rows": 1}}},
    )
    project.set_asset_placement(tileset.id, "ram2", 0)

    level = {"tileset": "tileset", "width": 2, "height": 1, "tiles": [[0, 1]]}
    (project.folder / "level1.map.json").write_text(json.dumps(level))
    level_entry = project.add_asset("level1.map.json", AssetKind.TILEMAP, symbol="level1")
    project.set_asset_placement(level_entry.id, "ram3", 0)

    text = regenerate_assets_asm(project).read_text()
    assert "level1_WIDTH: equ 2" in text
    assert "level1_HEIGHT: equ 1" in text
    assert "; tileset: tileset" in text
    assert cache_path(project, "level1").read_bytes() == bytes([0, 1])


def test_regenerate_assets_asm_tilemap_bad_tileset_reference_raises(tmp_path):
    import json

    project = _project(tmp_path)
    level = {"tileset": "does_not_exist", "width": 1, "height": 1, "tiles": [[0]]}
    (project.folder / "level1.map.json").write_text(json.dumps(level))
    entry = project.add_asset("level1.map.json", AssetKind.TILEMAP, symbol="level1")
    project.set_asset_placement(entry.id, "ram2", 0)
    with pytest.raises(AssetBuildError, match="unknown tileset"):
        regenerate_assets_asm(project)


def test_regenerate_assets_asm_native_sprite_emits_attr_offset(tmp_path):
    import json as json_module

    from zxemu_core.assets.native_sprite import NATIVE_SUFFIX, blank_sprite_data

    project = _project(tmp_path)
    path = project.folder / f"hero{NATIVE_SUFFIX}"
    path.write_text(json_module.dumps(blank_sprite_data(8, 8)))
    entry = project.add_asset(f"hero{NATIVE_SUFFIX}", AssetKind.SPRITE_SHEET, symbol="hero")
    project.set_asset_placement(entry.id, "ram2", 0)

    text = regenerate_assets_asm(project).read_text()
    assert "hero_ATTR_OFFSET: equ 8" in text  # 8-byte pixel plane, attrs start right after
    assert "hero_FRAME_STRIDE: equ 9" in text  # 8 pixel bytes + 1 attr byte


def test_regenerate_assets_asm_sprite_sheet_with_generate_attrs(tmp_path):
    project = _project(tmp_path)
    (project.folder / "sprite.bmp").write_bytes(write_bmp24(8, 8, lambda x, y: (0, 0, 0)))
    entry = project.add_asset(
        "sprite.bmp", AssetKind.SPRITE_SHEET, symbol="sprite",
        params={
            "frame_width": 8, "frame_height": 8, "layout": {"grid": {"cols": 1, "rows": 1}},
            "generate_attrs": True,
        },
    )
    project.set_asset_placement(entry.id, "ram2", 0)

    text = regenerate_assets_asm(project).read_text()
    assert "sprite_ATTR_OFFSET: equ 8" in text


# --------------------------------------------------------------------------------
# reserved_code_ranges / resolve_auto_placements avoiding known code
# --------------------------------------------------------------------------------


def test_coalesce_addresses_merges_nearby():
    assert _coalesce_addresses({100, 103, 106}) == [(100, 10)]


def test_coalesce_addresses_splits_far_apart():
    assert _coalesce_addresses({100, 500}) == [(100, 4), (500, 4)]


def test_reserved_code_ranges_empty_without_a_previous_build(tmp_path):
    project = _project(tmp_path)
    assert reserved_code_ranges(project) == {}


def test_reserved_code_ranges_reads_the_previous_builds_sld_on_48k(tmp_path):
    project = _project(tmp_path, "48k")
    sld_text = "main.asm|10||0|2|32768|T|\nmain.asm|11||0|2|32772|T|\n"
    _sld_path(project).write_text(sld_text)
    assert reserved_code_ranges(project) == {"ram2": [(0, 8)]}  # offsets 0,4 within ram2 (base $8000)


def test_reserved_code_ranges_skips_the_ambiguous_128k_slot(tmp_path):
    # Slot 3 on 128K could be any of 8 banks depending on runtime paging the SLD
    # can't see -- deliberately not reserved (see the module docstring).
    project = _project(tmp_path, "128k")
    _sld_path(project).write_text("main.asm|10||0|3|49152|T|\n")
    assert reserved_code_ranges(project) == {}


def test_reserved_code_ranges_covers_the_fixed_128k_slots(tmp_path):
    project = _project(tmp_path, "128k")
    sld_text = "main.asm|10||0|1|16384|T|\nmain.asm|11||0|2|32768|T|\n"
    _sld_path(project).write_text(sld_text)
    assert reserved_code_ranges(project) == {"ram5": [(0, 4)], "ram2": [(0, 4)]}


def test_resolve_auto_placements_avoids_previously_seen_code(tmp_path):
    # Reproduces the exact collision hit twice in live testing: a fresh asset
    # auto-locating to ram2 offset 0, exactly where the template's own code begins.
    project = _project(tmp_path, "48k")
    _sld_path(project).write_text("main.asm|10||0|2|32768|T|\n")  # ram2 offset 0 is known code
    project.add_asset("a.bin", AssetKind.BINARY, symbol="a")

    resolve_auto_placements(project)

    placement = project.assets()[0].placement
    assert not (placement["bank"] == "ram2" and placement["offset"] < 4)
