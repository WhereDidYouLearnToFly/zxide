"""Build the right emulated machine for a project's model (48K, 128K or Pentagon).

A zxide project declares a machine model; opening it swaps the running machine to
match (see MainWindow.set_machine). Both the app's composition root (main.py) and
that swap go through :func:`build_machine`, so ROM loading and model selection live
in exactly one place.
"""

from __future__ import annotations

import importlib.resources as res

from zxemu_core.machine import Machine, Machine128, MachinePentagon


def _rom(name: str) -> bytes:
    return (res.files("zxemu_core") / "roms" / name).read_bytes()


def load_48_rom() -> bytes:
    """The 48K BASIC ROM."""
    return _rom("48.rom")


def load_128_roms() -> tuple[bytes, bytes]:
    """The two 128K ROMs: (ROM0 = 128 editor/menu, ROM1 = 48 BASIC)."""
    return _rom("128-0.rom"), _rom("128-1.rom")


def load_pentagon_roms() -> tuple[bytes, bytes]:
    """The Pentagon's two ROMs: (ROM0 = the TR-DOS-aware 128 menu, ROM1 = 48 BASIC).

    ROM1 is byte-identical to the Sinclair 128's; the clone only patched ROM0, where 65
    bytes turn the "Tape Tester" menu entry into "TR-DOS" and add the code that enters it
    via ``RANDOMIZE USR 15616``. See TRDOS.md, and roms/LICENSE-roms.txt for the licensing
    position on this pair, which is *not* the same as the Amstrad ROMs'.
    """
    return _rom("128p-0.rom"), _rom("128p-1.rom")


def load_trdos_rom() -> bytes:
    """TR-DOS: the Beta 128 interface's own 16K ROM, paged in over ROM at 0x0000."""
    return _rom("trdos.rom")


def build_machine(model: str):
    """Construct the machine for ``model`` ("48k", "128k" or "pentagon").

    Unknown models fall back to 48K rather than raising: the model comes out of a
    project manifest a human may have edited, and an unrecognised string should open the
    project on the safest machine rather than refuse to open it at all.
    """
    if model == "pentagon":
        return MachinePentagon(*load_pentagon_roms(), load_trdos_rom())
    if model == "128k":
        return Machine128(*load_128_roms())
    return Machine(load_48_rom())


def machine_model(machine) -> str:
    """The model string for a live machine -- the inverse of ``build_machine``.

    Pentagon is tested first because it *subclasses* Machine128, so the obvious order
    would quietly report every Pentagon as a 128K.
    """
    if isinstance(machine, MachinePentagon):
        return "pentagon"
    return "128k" if isinstance(machine, Machine128) else "48k"
