import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_zexall import FIXTURES_DIR, run_com_file  # noqa: E402


def _fixture_or_skip(name: str):
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present in {FIXTURES_DIR} -- see fixtures/README.md")
    return path


def test_zexdoc():
    output = run_com_file(_fixture_or_skip("zexdoc.com"))
    assert "error" not in output.lower(), output


def test_zexall():
    output = run_com_file(_fixture_or_skip("zexall.com"))
    assert "error" not in output.lower(), output
