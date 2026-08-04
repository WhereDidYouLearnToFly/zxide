"""Reading a memory plan out of assembly source (zxemu_core.debug.asm_layout).

What is worth pinning here is not the byte arithmetic -- ``asm_meter`` owns that and has
its own tests -- but the *layout* rules: where a region starts and stops, what names it,
which bank it lands in, and above all when the scanner admits it is guessing. A length
that is quietly wrong is the failure mode this module exists to avoid, so most of these
tests are about the ``estimated``/``ambiguous_bank`` flags rather than the numbers.
"""

from __future__ import annotations

from zxemu_core.debug import asm_layout


def _scan(source, model="48k", **kwargs):
    return asm_layout.scan(source, model, **kwargs)


def test_org_opens_a_region_named_by_its_first_label():
    source = "    org $8000\nstart:\n    ld a,1\n    ret\n"
    regions = _scan(source).regions
    assert len(regions) == 1
    assert (regions[0].name, regions[0].address, regions[0].bank, regions[0].offset) == ("start", 0x8000, "ram2", 0)
    assert regions[0].length == 3  # ld a,n is 2 bytes, ret is 1
    assert not regions[0].estimated


def test_module_names_the_region_in_either_order():
    """A MODULE names its region whether it opens before or after the org."""
    after = _scan("    org $8000\n    MODULE Player\nstart:\n    ret\n    ENDMODULE\n").regions
    before = _scan("    MODULE Player\n    org $8000\nstart:\n    ret\n    ENDMODULE\n").regions
    assert after[0].name == "Player"
    assert before[0].name == "Player"


def test_endmod_closes_a_module_like_endmodule():
    """sjasmplus' short spelling, which vendored third-party players are written with.

    Missing it is not a cosmetic gap: the module stack never unwinds, so every ``org``
    for the rest of the project inherits the name of whatever was included -- a plan
    showing seven blocks all called PTS, one per file that followed the player.
    """
    source = "    MODULE PTS\n    org $8400\n    ret\n    ENDMOD\n    org $9000\nafter:\n    ret\n"
    assert [region.name for region in _scan(source).regions] == ["PTS", "after"]


def test_nested_modules_join_with_dots():
    source = "    MODULE Game\n    MODULE Sprites\n    org $9000\n    ret\n    ENDMODULE\n    ENDMODULE\n"
    assert _scan(source).regions[0].name == "Game.Sprites"


def test_a_second_org_closes_the_first_region():
    source = "    org $8000\ncode:\n    ret\n    org $c000\ndata:\n    db 1,2,3,4\n"
    regions = _scan(source).regions
    assert [(r.name, r.address, r.length, r.kind) for r in regions] == [("code", 0x8000, 1, "code"), ("data", 0xC000, 4, "data")]


def test_bare_column_zero_label_still_names_and_counts():
    """`loop  ld a,1` -- a label with no colon, which only column zero distinguishes."""
    regions = _scan("    org $8000\nloop  ld a,1\n").regions
    assert (regions[0].name, regions[0].length) == ("loop", 2)


def test_org_with_nothing_after_it_is_not_a_region():
    assert _scan("    org $8000\n").regions == []


def test_unknown_macro_call_marks_the_region_estimated():
    source = "    org $8000\nstart:\n    ret\n    DRAW_SPRITE 4, 5\n"
    region = _scan(source).regions[0]
    assert region.estimated
    assert region.length == 1  # what it could price; honest about the rest via the flag


def test_macro_definition_body_emits_nothing():
    """A macro's body costs bytes where it is *called*, not where it is written."""
    source = "    org $8000\n    MACRO WAIT\n    ld b,0\n    djnz $\n    ENDM\nstart:\n    ret\n"
    region = _scan(source).regions[0]
    assert region.length == 1
    assert region.name == "start"


def test_repeat_and_conditional_blocks_are_estimates():
    assert _scan("    org $8000\n    DUP 4\n    nop\n    EDUP\n").regions[0].estimated
    assert _scan("    org $8000\n    IFDEF DEBUG\n    nop\n    ENDIF\n    ret\n").regions[0].estimated


def test_align_pads_to_the_next_boundary():
    source = "    org $8001\n    ALIGN 8\nafter:\n    ret\n"
    region = _scan(source).regions[0]
    assert region.length == 8  # 7 bytes of padding up to $8008, then the ret
    assert not region.estimated


def test_ds_reserves_space_without_guessing():
    region = _scan("    org $8000\nbuffer:\n    ds 256\n").regions[0]
    assert (region.length, region.kind, region.estimated) == (256, "data", False)


def test_48k_addresses_map_to_their_fixed_banks():
    source = "    org $4000\n    db 1\n    org $8000\n    db 1\n    org $c000\n    db 1\n"
    assert [region.bank for region in _scan(source).regions] == ["ram1", "ram2", "ram3"]


def test_128k_slot_three_is_ambiguous_without_a_page():
    region = _scan("    org $c000\n    db 1\n", model="128k").regions[0]
    assert region.ambiguous_bank
    assert region.bank == ""  # naming a bank here would be a guess about a port write


def test_page_directive_resolves_the_bank_and_splits_the_region():
    source = "    SLOT 3\n    PAGE 7\n    org $c000\ngfx:\n    db 1,2\n"
    region = _scan(source, model="128k").regions[0]
    assert (region.bank, region.ambiguous_bank, region.offset) == ("ram7", False, 0)


def test_page_change_mid_region_starts_a_new_one():
    """The same address in a different bank is a different place, so it is a new region."""
    source = "    SLOT 3\n    PAGE 1\n    org $c000\nfirst:\n    db 1\n    PAGE 3\n    db 2,3\n"
    regions = _scan(source, model="128k").regions
    assert [(r.bank, r.length) for r in regions] == [("ram1", 1), ("ram3", 2)]


def test_device_overrides_the_project_model():
    """A 48K device in a project opened as 128K assembles as a 48K, so the map must agree."""
    region = _scan("    device zxspectrum48\n    org $c000\n    db 1\n", model="128k").regions[0]
    assert (region.bank, region.ambiguous_bank) == ("ram3", False)


def test_pentagon_stays_pentagon_on_a_128_device():
    result = _scan("    device zxspectrum128\n    org $4000\n    db 1\n", model="pentagon")
    assert result.regions[0].bank == "ram5"  # the 128K map, not rewritten into a 48K's


def test_include_is_followed_with_the_cursor_where_it_was():
    sources = {"part.asm": "inner:\n    db 1,2,3\n"}
    result = _scan('    org $8000\nouter:\n    ret\n    include "part.asm"\n', read_source=sources.get)
    region = result.regions[0]
    assert region.length == 4  # 1 byte here, 3 in the include -- one continuous region
    assert result.missing_includes == []


def test_org_inside_an_include_opens_its_own_region_credited_to_that_file():
    sources = {"data.asm": "    org $c000\ntable:\n    db 1,2\n"}
    result = _scan('    org $8000\nmain:\n    ret\n    include "data.asm"\n', read_source=sources.get)
    assert [(r.name, r.origin, r.address) for r in result.regions] == [("main", "", 0x8000), ("table", "data.asm", 0xC000)]


def test_a_missing_include_is_reported_not_ignored():
    result = _scan('    org $8000\n    ret\n    include "nope.asm"\n', read_source=lambda path: None)
    assert result.missing_includes == ["nope.asm"]
    assert result.regions[0].estimated


def test_include_cycle_terminates():
    sources = {"a.asm": '    include "b.asm"\n', "b.asm": '    include "a.asm"\n'}
    result = _scan('    org $8000\n    ret\n    include "a.asm"\n', read_source=sources.get)
    assert result.regions[0].length == 1


def test_incbin_length_comes_from_the_file_not_a_guess():
    result = _scan('    org $8000\ngfx:\n    incbin "hero.bin"\n', file_size=lambda path: 1024)
    region = result.regions[0]
    assert (region.length, region.estimated) == (1024, False)


def test_incbin_honours_an_explicit_length_and_offset():
    explicit = _scan('    org $8000\n    incbin "x.bin",128,32\n', file_size=lambda path: 1024).regions[0]
    assert explicit.length == 32
    skipped = _scan('    org $8000\n    incbin "x.bin",100\n', file_size=lambda path: 1024).regions[0]
    assert skipped.length == 924


def test_incbin_of_an_unmeasurable_file_is_an_estimate():
    region = _scan('    org $8000\n    ret\n    incbin "missing.bin"\n', file_size=lambda path: None).regions[0]
    assert region.estimated


def test_bytes_before_any_org_land_at_zero():
    region = _scan("boot:\n    db 1,2\n").regions[0]
    assert (region.address, region.bank, region.name) == (0, "rom", "boot")


def test_comments_and_multi_statement_lines_are_handled():
    region = _scan("    org $8000\nstart: ld a,1 : ret  ; go\n").regions[0]
    assert (region.name, region.length) == ("start", 3)


# --- placement constraints the bytes cannot express ----------------------------------


def test_a_pin_comment_marks_the_next_org():
    region = _scan("; zxide: pin\n    org $8181\nim2routine:\n    ds 43\n").regions[0]
    assert region.pinned
    assert region.align == 0


def test_an_align_comment_records_its_boundary():
    region = _scan("; zxide: align 256\n    org $8200\nim2table:\n    ds 257\n").regions[0]
    assert (region.align, region.pinned) == (256, False)


def test_an_annotation_on_the_org_line_itself_counts():
    assert _scan("    org $8181   ; zxide: pin\n    ds 4\n").regions[0].pinned


def test_an_annotation_applies_to_one_org_only():
    source = "; zxide: pin\n    org $8000\nfirst:\n    ds 4\n    org $9000\nsecond:\n    ds 4\n"
    assert [region.pinned for region in _scan(source).regions] == [True, False]


def test_an_ordinary_comment_is_not_an_annotation():
    assert not _scan("; pin this one day\n    org $8000\n    ds 4\n").regions[0].pinned


def test_a_pin_carries_its_reason_to_whoever_asks():
    """So the next reader learns *why* it can't move, not just that it can't."""
    region = _scan("; zxide: pin IM2 handler -- address is the fill byte doubled\n    org $8181\n    ds 4\n").regions[0]
    assert region.reason == "IM2 handler -- address is the fill byte doubled"


def test_an_align_can_carry_a_reason_after_its_number():
    region = _scan("; zxide: align 256 the I register is only a high byte\n    org $8200\n    ds 4\n").regions[0]
    assert (region.align, region.reason) == (256, "the I register is only a high byte")


def test_a_declared_size_reserves_room_without_emitting_anything():
    """`; zxide: size` is the point of the feature: headroom that costs no output bytes."""
    region = _scan("; zxide: size 512 room to grow\n    org $5B00\n    MODULE globals\n    ENDMODULE\n").regions[0]
    assert (region.length, region.reserved, region.claimed) == (0, 512, 512)
    assert region.reason == "room to grow"


def test_a_block_that_emits_less_than_it_reserved_still_holds_the_reservation():
    region = _scan("; zxide: size 512\n    org $5D00\ncode:\n    ds 300\n").regions[0]
    assert (region.length, region.claimed, region.end) == (300, 512, 0x1D00 + 512)


def test_a_block_that_outgrows_its_reservation_claims_what_it_needs():
    """Otherwise the map would say everything fits while the assembler wrote past it."""
    region = _scan("; zxide: size 100\n    org $6000\nbig:\n    ds 400\n").regions[0]
    assert (region.length, region.reserved, region.claimed) == (400, 100, 400)


def test_reserve_is_accepted_as_a_spelling_of_size():
    assert _scan("; zxide: reserve 256\n    org $8000\n    MODULE m\n    ENDMODULE\n").regions[0].claimed == 256


def test_a_size_with_no_number_is_reported_rather_than_ignored():
    result = _scan("; zxide: size\n    org $8000\n    ds 4\n", origin="main.asm")
    assert result.regions[0].reserved == 0
    assert "size needs a number of bytes" in result.bad_annotations[0]
