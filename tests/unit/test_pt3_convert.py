"""Tests for the PT3 passthrough converter (zxemu_core.assets.pt3_convert)."""

from __future__ import annotations

import pytest

from zxemu_core.assets.pt3_convert import convert_pt3


def test_passthrough_with_valid_header():
    data = b"PT3" + b"\x00" * 20
    assert convert_pt3(data) == data


def test_rejects_missing_magic():
    with pytest.raises(ValueError, match="PT3"):
        convert_pt3(b"nope" + b"\x00" * 20)
