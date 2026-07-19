# zxide

A ZX Spectrum development IDE, built around a pure-Python emulator core and a
PyQt5 UI.

## Status

**Milestone 1 complete.** A from-scratch pure-Python Z80 CPU + 48K
memory/ULA/keyboard model, driven by a PyQt5 view that boots the bundled ROM,
runs BASIC, and takes keyboard input at real-time 50 fps. 207 tests pass; the
CPU is cross-checked against the FUSE reference emulator (see
`dev-support/STATUS.md` for the full state and what's next).

## Layout

- `main.py` — application entry point + frame loop (the IDE grows from here).
- `zxemu_core/` — the emulator core (CPU, memory, ULA, keyboard). No Qt
  dependency; independently testable.
  - `cpu/` — the Z80: `z80.py` (fetch/decode/execute loop), `registers.py`,
    `flags.py`, and `instructions/` (one explicit handler per opcode, grouped
    by family).
- `zxemu_ui/` — the PyQt5 UI layer (the live emulator view widget).
- `tests/` — unit, integration (ROM boot), and the zexdoc/zexall harness.
- `dev-support/` — status/handoff notes, screenshots, the ZEXALL binaries.

Each package's `__init__.py` opens with an educational overview — start there.

## Running

```
python main.py
```

Run it from a terminal (or "Run Without Debugging" / Ctrl+F5 in VS Code) — the
emulator's hot loop is far slower under a debugger's per-line tracing.

## Development

```
pip install -e ".[dev]"
pytest
```

## Licensing

Original code is MIT licensed (see `LICENSE`). Bundled ROM images under
`zxemu_core/roms/` are third-party binaries under separate terms — see
`zxemu_core/roms/LICENSE-roms.txt`.
