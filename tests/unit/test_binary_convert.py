"""Tests for the raw-binary passthrough converter (zxemu_core.assets.binary_convert)."""

from __future__ import annotations

import pytest

from zxemu_core.assets.binary_convert import convert_binary


def test_passthrough_returns_same_bytes():
    assert convert_binary(b"\x01\x02\x03") == b"\x01\x02\x03"


def test_accepts_matching_expected_length():
    assert convert_binary(b"\x01\x02", expected_length=2) == b"\x01\x02"


def test_rejects_mismatched_expected_length():
    with pytest.raises(ValueError, match="expected 3"):
        convert_binary(b"\x01\x02", expected_length=3)
