# zxide

A ZX Spectrum development IDE, built around a pure-Python emulator core and a
PyQt5 UI.

## Status

**Milestones 1–3 complete, plus a full debugger.** A from-scratch pure-Python Z80
CPU with 48K and 128K machine models (memory paging, ULA, keyboard, beeper,
AY-3-8912, `.tap` fast loading, `.sna` snapshots), wrapped in a dockable IDE with an
assembler build pipeline and a source-level debugger. 342 tests pass; the CPU is
cross-checked against the FUSE reference emulator. See `dev-support/STATUS.md` for
the full state and `DEV_PLAN.md` for what's next.

## Layout

- `main.py` — application entry point (composition root).
- `zxemu_core/` — the emulator, with no Qt dependency and independently testable.
  The machine itself is at the top level (`machine.py`, `memory.py`, `ula.py`,
  `keyboard.py`); everything else is grouped by subsystem:
  - `cpu/` — the Z80: `z80.py` (fetch/decode/execute), `registers.py`, `flags.py`,
    and `instructions/` (one explicit handler per opcode, grouped by family).
  - `sound/` — `beeper.py`, `ay.py`, and the `mixer.py` that sums them.
  - `storage/` — `tape.py`, `snapshot.py`.
  - `debug/` — `disassembler.py`, `rom_symbols.py`, `debug_expr.py`, `analysis.py`.
- `zxemu_ui/` — the PyQt5 layer. Shell at the top level (`main_window.py`,
  `controller.py`, `editor.py`, …), plus:
  - `panels/` — the dockable views: screen, registers, memory, disassembly,
    call stack, analysis.
  - `workspace/` — your project rather than the machine: manifest, settings,
    sjasmplus build, and the SLD source map.
- `tests/` — unit, integration (ROM boot), and the zexdoc/zexall harness.
- `dev-support/` — status/handoff notes, screenshots, the ZEXALL binaries.

**Each package's `__init__.py` opens with an educational overview — start there.**
Individual modules carry the reasoning: not just what the code does, but why it is
built that way and where the approach stops working.

## Running

```
python main.py
```

Run it from a terminal (or "Run Without Debugging" / Ctrl+F5 in VS Code) — the
emulator's hot loop is far slower under a debugger's per-line tracing.

## Using the IDE

Menus are grouped by what you're doing rather than by which code implements them:

| menu | for |
|---|---|
| **File** | projects and source files |
| **Build** | turning *your* project into a running program |
| **Load** | running *someone else's* — a `.sna` snapshot or `.tap` tape |
| **Model** | which machine is emulated (48K / 128K), switchable any time |
| **Disassembly** | the disassembly panel and where it points |
| **Breaks** | breakpoint conditions, run-to-cursor |
| **Watch** | pause when a value or port is *touched* |
| **Reversing** | understanding someone else's program: search, cross-references, coverage, trace |
| **Compression** | optional addons (ZX0) copied into the open project |
| **View** | panel visibility, interface scale, saved dock layout |

### Keyboard

| key | action |
|---|---|
| `F5` | Build & Debug (breakpoints active) |
| `Ctrl+F5` | Build & Run (breakpoints ignored) |
| `F11` | Step Into — one instruction, entering calls |
| `F10` | Step Over — run calls and block ops to completion |
| `Shift+F11` | Step Out — run until the current subroutine returns |
| `Ctrl+F10` | Run to Cursor |
| `Ctrl+S` / `Ctrl+Shift+S` | Save / Save All |

### Debugging

Click the editor gutter to set a breakpoint; **Build ▸ Build & Debug** honours them.
While paused you can edit as well as inspect — poke a byte in the Memory panel, click
a register to set it, hover a flag to read what it means.

Beyond that: **watchpoints** on memory reads *and* writes and on I/O ports;
**conditional breakpoints** (`A == $FF`, `(HL) == 0`, `B == 0 and C == 0`); a
**disassembly** panel annotated with ROM routine names and your own labels from the
build; an inferred **call stack**; **coverage** recording and a bounded **execution
trace**; and memory **search** and **cross-references**.

Some of these answer with certainty and some with inference, and the panels say
which — a call stack is reconstructed rather than recorded, cross-references are a
static scan that cannot follow computed jumps, and an address absent from coverage
means "not executed *yet*", never "unreachable".

## Development

```
pip install -e ".[dev]"
pytest
```

## Licensing

Original code is MIT licensed (see `LICENSE`). Bundled ROM images under
`zxemu_core/roms/` are third-party binaries under separate terms — see
`zxemu_core/roms/LICENSE-roms.txt`. The optional ZX0 decompressor in
`zxemu_ui/addons/zx0addon/` is third-party (zlib licence); see its header.
