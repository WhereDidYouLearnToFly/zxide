# zxide — project status & handoff

_Last updated: 2026-07-18._ A snapshot to make it easy to pick the project back up.

## Where we are

**Milestone 1 (emulator core + live PyQt5 view) is complete and working.**
- Pure-Python Z80 CPU (full instruction set incl. undocumented behaviour),
  48K memory, ULA (timing/contention/border), 8x5 keyboard.
- PyQt5 view renders the screen (bitmap + attributes + border + FLASH) via a
  numpy fast path, driven by a real-time-paced frame loop at ~50 fps.
- Boots the real 48K ROM to the 1982 copyright screen; BASIC runs; typing
  `PRINT "HELLO"` works end to end.
- **207 tests pass** (`pytest tests/unit tests/integration`).

## How it's structured

```
main.py            entry point + frame loop (QTimer, real-time catch-up pacing)
zxemu_core/        emulator core, no Qt dependency
  cpu/
    z80.py         fetch/decode/execute loop, interrupts, HALT
    registers.py   registers + flag bits
    flags.py       ALU/flag math
    instructions/  one explicit handler per opcode, grouped by family
                   (load8/16, arith8/16, logic in arith8, rotate_shift, bit,
                    jump, call_return, control, blockio, exchange, indexed)
                   + indexed_bit.py (DDCB/FDCB, kept compact as a loop demo)
                   + _dispatch.py (tables + @base/@cb/@ed/@indexed decorators)
  memory.py        16K-bank paged model (paging-ready for 128K)
  ula.py           port 0xFE (border/keyboard), frame timing, contention table
  keyboard.py      8x5 matrix
  machine.py       wires it together; run_frame() = one 50Hz frame
zxemu_ui/
  emulator_view.py QWidget: screen render + PC-key -> Spectrum-matrix mapping
tests/             unit, integration (ROM boot), zexall harness
dev-support/       this file, screenshots, ZEXALL binaries (git-ignored .com)
```

Design intent: the core is UI-agnostic and the instruction handlers are
spelled out explicitly for **educational readability** (a learner can search a
mnemonic and read its code). Each package `__init__.py` is an educational
overview. When the IDE grows, `main.py` becomes the IDE shell and
`zxemu_ui`'s view becomes one dockable panel.

## Key decisions made

- **Fresh pure-Python emulator**, not a port of FUSE. FUSE (`E:/github/fuse`,
  GPLv2) is used only as a reference. Only the ROM binaries are reused.
- **PyQt5** UI; **numpy** for fast rendering.
- **48K first, designed for 128K** (paged memory abstraction already in place;
  `128-0.rom`/`128-1.rom` bundled but not wired up).
- **No built-in code editor** planned — the IDE will open sources in an
  external editor and build via an external assembler (Milestone 2).
- Instruction tables refactored to explicit per-family files; DDCB/FDCB kept
  generated on purpose as a contrast/demo.

## Known limitations / deferred (not bugs)

- **zexdoc/zexall not fully run** — impractically slow in CPython (~5B
  instructions / ~3h and still not done, zero errors seen). A FUSE
  cross-audit confirmed no observable-behaviour bugs. Full pass would need
  PyPy or an overnight run.
- **3 undocumented-flag simplifications** (don't affect real software; marked
  with `# NOTE:` in code): SCF/CCF X/Y sourced from A (no `Q` register);
  BIT b,(HL) X/Y from `(HL+1)>>8` instead of MEMPTR; EI enables interrupts
  immediately (no 1-instruction delay).
- **Block instructions run atomically** (whole LDIR/CPIR/etc. in one step) —
  a deliberate speed trade-off; no mid-block interrupts.
- **Timing** is functional, not cycle-accurate: contention is modelled/tested
  but not applied to every memory access; no per-scanline border effects.
- **Not a git repo yet** (user is handling version control separately).

## Performance notes

- ~12 ms to emulate one frame + ~0.5 ms to render → comfortable 50 fps.
- **Run without a debugger.** Under VS Code's debugger (F5) the per-line trace
  hook makes the CPU loop ~6x slower (~13 fps). Use `python main.py` or
  Ctrl+F5 ("Run Without Debugging"). The window title shows a live
  fps / timer / emulate-ms readout.

## Likely next steps

1. **Milestone 2 — the IDE shell**: project system, external-editor hookup,
   external assembler build → load into the emulator view. Move the frame
   pump out of the window into a controller (start/stop/pause/reset/step).
2. **128K machine** via the existing paging abstraction (port 0x7ffd, AY, 2nd
   ROM) as a `Machine` subclass.
3. Optional: full zexall pass under PyPy; fix the 3 undocumented-flag items if
   strict conformance is ever wanted; a debugger panel (registers/memory).
