"""Tests for the Z80 Assembly Meter (zxemu_core.debug.asm_meter).

The instruction costs here are the published Z80 figures. They are spot-checked rather
than exhaustively enumerated -- the table is the specification, so re-listing all of it
in a test would only prove the table equals itself. What is worth pinning is one case per
*shape* (register, immediate, indirect, indexed, prefixed), the branch ranges, and the
source-parsing rules, which is where the real risk of being wrong lives.
"""

from __future__ import annotations

import pytest

from zxemu_core.debug.asm_meter import (
    MeterResult,
    classify,
    directive_bytes,
    format_result,
    instruction_cost,
    measure,
    measure_statement,
    parse_number,
    strip_comment,
)


def _cost(source: str) -> tuple[int, int, int]:
    """``(bytes, T-min, T-max)`` for a single instruction written as source."""
    result = measure_statement(source)
    assert result.unknown == 0, f"{source!r} was not recognised"
    return result.code_bytes, result.t_states_min, result.t_states_max


# --- one case per instruction shape ----------------------------------------------------


@pytest.mark.parametrize(
    "source,expected",
    [
        # 8-bit loads
        ("ld a,b", (1, 4, 4)),
        ("ld a,$ff", (2, 7, 7)),
        ("ld a,(hl)", (1, 7, 7)),
        ("ld (hl),a", (1, 7, 7)),
        ("ld (hl),5", (2, 10, 10)),
        ("ld a,(bc)", (1, 7, 7)),
        ("ld (de),a", (1, 7, 7)),
        ("ld a,($5c00)", (3, 13, 13)),
        ("ld ($5c00),a", (3, 13, 13)),
        ("ld a,i", (2, 9, 9)),
        ("ld r,a", (2, 9, 9)),
        # indexed
        ("ld a,(ix+3)", (3, 19, 19)),
        ("ld (iy-2),b", (3, 19, 19)),
        ("ld (ix+0),$40", (4, 19, 19)),
        # 16-bit loads
        ("ld hl,$8000", (3, 10, 10)),
        ("ld sp,$ff00", (3, 10, 10)),
        ("ld ix,$8000", (4, 14, 14)),
        ("ld hl,($5c00)", (3, 16, 16)),
        ("ld de,($5c00)", (4, 20, 20)),
        ("ld ($5c00),hl", (3, 16, 16)),
        ("ld ($5c00),bc", (4, 20, 20)),
        ("ld ($5c00),ix", (4, 20, 20)),
        ("ld sp,hl", (1, 6, 6)),
        ("ld sp,ix", (2, 10, 10)),
        # stack and exchange
        ("push bc", (1, 11, 11)),
        ("pop af", (1, 10, 10)),
        ("push ix", (2, 15, 15)),
        ("pop iy", (2, 14, 14)),
        ("ex de,hl", (1, 4, 4)),
        ("ex af,af'", (1, 4, 4)),
        ("ex (sp),hl", (1, 19, 19)),
        ("ex (sp),ix", (2, 23, 23)),
        ("exx", (1, 4, 4)),
        # 8-bit arithmetic, with and without the explicit destination
        ("add a,b", (1, 4, 4)),
        ("add b", (1, 4, 4)),
        ("add a,5", (2, 7, 7)),
        ("sub 5", (2, 7, 7)),
        ("cp (hl)", (1, 7, 7)),
        ("xor a", (1, 4, 4)),
        ("and (ix+1)", (3, 19, 19)),
        # 16-bit arithmetic
        ("add hl,de", (1, 11, 11)),
        ("adc hl,bc", (2, 15, 15)),
        ("sbc hl,sp", (2, 15, 15)),
        ("add ix,de", (2, 15, 15)),
        # increment / decrement
        ("inc a", (1, 4, 4)),
        ("inc (hl)", (1, 11, 11)),
        ("inc (ix+4)", (3, 23, 23)),
        ("inc hl", (1, 6, 6)),
        ("dec ix", (2, 10, 10)),
        # rotates and bit operations
        ("rlca", (1, 4, 4)),
        ("srl a", (2, 8, 8)),
        ("rl (hl)", (2, 15, 15)),
        ("sla (ix+1)", (4, 23, 23)),
        ("bit 7,a", (2, 8, 8)),
        ("bit 0,(hl)", (2, 12, 12)),
        ("bit 3,(iy+2)", (4, 20, 20)),
        ("set 1,b", (2, 8, 8)),
        ("res 2,(hl)", (2, 15, 15)),
        ("set 4,(ix+0)", (4, 23, 23)),
        # control flow, unconditional
        ("jp $8000", (3, 10, 10)),
        ("jp (hl)", (1, 4, 4)),
        ("jp (ix)", (2, 8, 8)),
        ("jr label", (2, 12, 12)),
        ("call $8000", (3, 17, 17)),
        ("ret", (1, 10, 10)),
        ("reti", (2, 14, 14)),
        ("rst $38", (1, 11, 11)),
        # misc
        ("nop", (1, 4, 4)),
        ("halt", (1, 4, 4)),
        ("di", (1, 4, 4)),
        ("neg", (2, 8, 8)),
        ("im 1", (2, 8, 8)),
        ("rld", (2, 18, 18)),
        # I/O
        ("in a,($fe)", (2, 11, 11)),
        ("in b,(c)", (2, 12, 12)),
        ("out ($fe),a", (2, 11, 11)),
        ("out (c),d", (2, 12, 12)),
        # block moves
        ("ldi", (2, 16, 16)),
        ("cpd", (2, 16, 16)),
        # the undocumented index halves
        ("ld a,ixh", (2, 8, 8)),
        ("ld iyl,5", (3, 11, 11)),
        ("inc ixh", (2, 8, 8)),
        ("add a,ixl", (2, 8, 8)),
    ],
)
def test_instruction_cost(source, expected):
    assert _cost(source) == expected


# --- the cases where time is a range ----------------------------------------------------


@pytest.mark.parametrize(
    "source,expected",
    [
        ("jr nz,loop", (2, 7, 12)),     # 12T taken, 7T not
        ("djnz loop", (2, 8, 13)),      # 13T while B is non-zero, 8T on the last pass
        ("call z,routine", (3, 10, 17)),
        ("ret c", (1, 5, 11)),
        ("ldir", (2, 16, 21)),          # 21T per iteration, 16T on the one that ends it
        ("cpir", (2, 16, 21)),
        ("otir", (2, 16, 21)),
    ],
)
def test_branching_costs_are_a_range(source, expected):
    assert _cost(source) == expected


def test_an_unconditional_jump_is_not_a_range():
    result = measure_statement("jp $8000")
    assert not result.has_time_range


def test_a_conditional_jump_is_a_range():
    assert measure_statement("jr z,loop").has_time_range


# --- the c / condition ambiguity ---------------------------------------------------------


def test_c_is_a_register_in_a_load():
    assert _cost("ld c,a") == (1, 4, 4)


def test_c_is_a_condition_in_a_jump():
    assert _cost("jp c,$8000") == (3, 10, 10)


def test_c_is_a_condition_in_a_return():
    assert _cost("ret c") == (1, 5, 11)


def test_c_is_a_port_in_an_out():
    assert _cost("out (c),a") == (2, 12, 12)


# --- operand classification ---------------------------------------------------------------


@pytest.mark.parametrize(
    "operand,tag",
    [
        ("a", "a"), ("b", "r8"), ("hl", "rp"), ("af", "rp2"), ("ix", "ii"),
        ("(hl)", "(hl)"), ("(ix+1)", "(i+d)"), ("(iy-3)", "(i+d)"), ("($4000)", "(nn)"),
        ("(c)", "(c)"), ("nz", "cc"), ("ixh", "rx"), ("label", "n"), ("$ff", "n"),
    ],
)
def test_classify(operand, tag):
    assert tag in classify(operand)


def test_a_bare_index_register_in_parens_is_both_a_jump_target_and_a_zero_displacement():
    assert "(ii)" in classify("(ix)")
    assert "(i+d)" in classify("(ix)")


def test_classification_is_case_insensitive():
    assert classify("HL") == classify("hl")
    assert _cost("LD A,(HL)") == (1, 7, 7)


# --- invalid or unknown -------------------------------------------------------------------


def test_an_invalid_operand_combination_is_unknown_not_zero():
    assert measure_statement("ld b,($5c00)").unknown == 1


def test_an_unknown_mnemonic_is_counted_as_unknown():
    result = measure_statement("drawsprite hero, 4")
    assert result.unknown == 1
    assert result.code_bytes == 0 and result.t_states_min == 0


def test_instruction_cost_returns_none_for_a_non_instruction():
    assert instruction_cost("frobnicate", []) is None


# --- data directives -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,expected",
    [
        ("db 1,2,3", 3),
        ("defb $ff", 1),
        ('db "hello"', 5),
        ('db "hi", 0', 3),
        ("dw 1,2", 4),
        ("defw $8000", 2),
        ("ds 16", 16),
        ("defs 256", 256),
        ("dd 1", 4),
    ],
)
def test_data_directives_count_bytes(source, expected):
    result = measure_statement(source)
    assert result.data_bytes == expected
    assert result.instructions == 0
    assert result.t_states_min == 0  # data costs space, not time


@pytest.mark.parametrize("source", ["org $8000", "equ 5", "device zxspectrum48", "if DEBUG", "endif"])
def test_directives_that_emit_nothing_cost_nothing(source):
    result = measure_statement(source)
    assert result.data_bytes == 0 and result.unknown == 0


def test_a_reserve_directive_with_an_expression_is_unknown_rather_than_zero():
    """Better to say "I can't count this" than to silently report the block as free."""
    assert measure_statement("ds COUNT*2").unknown == 1


def test_directive_bytes_returns_none_for_a_non_directive():
    assert directive_bytes("wibble", []) is None


@pytest.mark.parametrize(
    "token,value",
    [("42", 42), ("$ff", 255), ("#ff", 255), ("0xff", 255), ("0ffh", 255),
     ("%1010", 10), ("0b1010", 10), ("1010b", 10), ("1_000", 1000)],
)
def test_parse_number(token, value):
    assert parse_number(token) == value


def test_parse_number_of_a_label_is_none():
    assert parse_number("counter") is None


# --- source parsing -------------------------------------------------------------------------


def test_strip_comment_removes_a_semicolon_comment():
    assert strip_comment("ld a,1 ; set it").strip() == "ld a,1"


def test_strip_comment_removes_a_double_slash_comment():
    assert strip_comment("ld a,1 // set it").strip() == "ld a,1"


def test_strip_comment_leaves_a_semicolon_inside_a_string():
    assert 'db "a;b"' == strip_comment('db "a;b"')


def test_a_comment_only_line_costs_nothing():
    assert measure("; just a note\n").total_bytes == 0


def test_a_colon_label_does_not_hide_the_instruction_beside_it():
    assert measure("loop: ld a,1\n").code_bytes == 2


def test_a_lone_colon_label_costs_nothing():
    result = measure("loop:\n")
    assert result.total_bytes == 0 and result.unknown == 0


def test_a_bare_column_zero_label_does_not_hide_the_instruction():
    assert measure("start   ld a,1\n").code_bytes == 2


def test_an_indented_instruction_is_never_mistaken_for_a_label():
    assert measure("    ld a,1\n").code_bytes == 2


def test_a_column_zero_equate_keeps_its_directive():
    result = measure("SCREEN equ $4000\n")
    assert result.unknown == 0 and result.total_bytes == 0


def test_several_statements_on_one_line_are_all_counted():
    assert measure("    ld a,1 : ld b,2 : nop\n").code_bytes == 5


def test_a_colon_inside_a_string_does_not_split_the_statement():
    assert measure('    db "a:b:c"\n').data_bytes == 5


def test_a_comma_inside_parentheses_does_not_split_an_operand():
    assert _cost("ld a,(ix+1)") == (3, 19, 19)


def test_tabs_separate_a_mnemonic_from_its_operands():
    assert measure("\tld\ta,(hl)\n").code_bytes == 1


def test_blank_lines_cost_nothing():
    assert measure("\n\n   \n").total_bytes == 0


# --- whole-run totals -----------------------------------------------------------------------


def test_measure_sums_a_routine():
    source = """
    ; copy B bytes from HL to DE
copy:
    ld a,(hl)
    ld (de),a
    inc hl
    inc de
    djnz copy
    ret
"""
    result = measure(source)
    assert result.instructions == 6
    assert result.code_bytes == 1 + 1 + 1 + 1 + 2 + 1
    assert result.t_states_min == 7 + 7 + 6 + 6 + 8 + 10
    assert result.t_states_max == 7 + 7 + 6 + 6 + 13 + 10
    assert result.unknown == 0


def test_measure_counts_code_and_data_together_in_the_total():
    result = measure("    ld a,1\n    db 1,2,3,4\n")
    assert result.code_bytes == 2
    assert result.data_bytes == 4
    assert result.total_bytes == 6


def test_measure_of_empty_source_is_all_zeroes():
    result = measure("")
    assert result == MeterResult()


# --- the status-bar summary --------------------------------------------------------------------


def test_format_result_leads_with_the_timing():
    assert format_result(measure("    ld a,1\n    nop\n")) == "11 T · 3 bytes · 2 instr"


def test_format_result_can_drop_the_timing():
    """What the whole-file readout asks for: summing a file's instructions costs nothing real."""
    assert format_result(measure("    ld a,1\n    nop\n"), timing=False) == "3 bytes · 2 instr"


def test_format_result_shows_a_range_when_a_branch_makes_one():
    assert "7–12 T" in format_result(measure("    jr nz,loop\n"))


def test_format_result_uses_the_singular_for_one_byte():
    assert "1 byte ·" in format_result(measure("    nop\n"))


def test_format_result_of_data_only_omits_the_timing():
    assert format_result(measure("    db 1,2,3\n")) == "3 bytes"


def test_format_result_flags_what_it_could_not_read():
    assert "1 unrecognised" in format_result(measure("    ld a,1\n    drawsprite hero\n"))


def test_format_result_of_nothing_is_empty():
    assert format_result(measure("; just a comment\n")) == ""
