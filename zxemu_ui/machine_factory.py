"""Build the right emulated machine for a project's model (48K or 128K).

A zxide project declares a machine model; opening it swaps the running machine to
match (see MainWindow.set_machine). Both the app's composition root (main.py) and
that swap go through :func:`build_machine`, so ROM loading and model selection live
in exactly one place.
"""

from __future__ import annotations

import importlib.resources as res

from zxemu_core.machine import Machine, Machine128


def _rom(name: str) -> bytes:
    return (res.files("zxemu_core") / "roms" / name).read_bytes()


def load_48_rom() -> bytes:
    """The 48K BASIC ROM."""
    return _rom("48.rom")


def load_128_roms() -> tuple[bytes, bytes]:
    """The two 128K ROMs: (ROM0 = 128 editor/menu, ROM1 = 48 BASIC)."""
    return _rom("128-0.rom"), _rom("128-1.rom")


def build_machine(model: str):
    """Construct the machine for ``model`` ("48k" or "128k"); unknown models are 48K."""
    if model == "128k":
        return Machine128(*load_128_roms())
    return Machine(load_48_rom())


def machine_model(machine) -> str:
    """The model string for a live machine -- the inverse of ``build_machine``."""
    return "128k" if isinstance(machine, Machine128) else "48k"
