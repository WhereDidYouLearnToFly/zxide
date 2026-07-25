"""Every package's ``__init__`` overview must mention every module beside it.

In this project the package ``__init__`` docstring *is* the documentation -- the README
says so ("Each package's `__init__.py` opens with an educational overview — start there"),
and a reader is expected to meet a subsystem through it. That makes it code with a
correctness property, and nothing was checking it.

The property is deliberately weak: only that each module's *name* appears somewhere in
its package's overview. It cannot judge whether the prose is any good, and it must not
try -- a test that nags about wording would be rewritten to shut it up within a week.
What it does catch is the failure that actually happens: somebody adds a module and the
overview silently stops describing the package.

That is not hypothetical. Four overviews had drifted by the time this was written --
``zxemu_core`` still said the emulator was "both the 48K and the 128K" with a Pentagon
sitting in ``machine.py``, ``storage`` said "two kinds of file" with three, ``zxemu_ui``
described ``media.py`` as handling ".sna/.z80 vs .tap/.tzx" long after disks arrived, and
``cpu`` described ``z80.py`` without either of the hooks hardware hangs off. All four were
found by hand, which is exactly the sort of thing that only gets done once.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PACKAGE_ROOTS = ("zxemu_core", "zxemu_ui")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _packages() -> list[Path]:
    found: list[Path] = []
    for root in PACKAGE_ROOTS:
        found += [init.parent for init in sorted((REPO_ROOT / root).rglob("__init__.py"))]
    return found


def _contents(package: Path) -> list[str]:
    """The modules and subpackages a reader would expect the overview to cover."""
    modules = [p.stem for p in sorted(package.glob("*.py")) if p.name != "__init__.py"]
    subpackages = [d.name for d in sorted(package.iterdir())
                   if d.is_dir() and (d / "__init__.py").exists()]
    return modules + subpackages


@pytest.mark.parametrize("package", _packages(), ids=lambda p: p.name)
def test_the_overview_mentions_everything_in_the_package(package):
    overview = (package / "__init__.py").read_text(encoding="utf-8")
    missing = [name for name in _contents(package) if name not in overview]
    assert not missing, (
        f"{package.relative_to(REPO_ROOT)}/__init__.py does not mention: {missing}. "
        "Add them to the package overview -- it is how a reader is meant to find them."
    )


def test_every_package_actually_has_an_overview():
    """An ``__init__`` that is empty or a bare import list is the same drift, further along."""
    thin = []
    for package in _packages():
        text = (package / "__init__.py").read_text(encoding="utf-8").lstrip()
        if not text.startswith(('"""', "'''")) or len(text) < 200:
            thin.append(str(package.relative_to(REPO_ROOT)))
    assert not thin, f"packages with no real overview docstring: {thin}"
