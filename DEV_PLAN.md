# zxide — Development Plan (Milestone 2: the IDE shell)

zxide is becoming a **"Unity for ZX Spectrum"**: an IDE built around the Milestone-1
emulator core. Milestone 1 (a working pure-Python Z80 core + live PyQt5 view) is done — see
`dev-support/STATUS.md`. This document plans Milestone 2, where the single emulator window
grows into a full IDE shell, and records the architecture decisions behind it so intent
survives between work sessions.

The raw original vision notes are preserved verbatim at the end ("Appendix: original vision").

---

## The shape of the IDE

A dockable, rearrangeable shell, Visual-Studio-style. A `File` menu owns project entry
(New / Open Project / Open Folder / Recent); the emulator carries its own control strip.

```
┌────────────────────────────────────────────────────────────────────┐
│ File  View  Build  Debug  Help                              (menu)  │
├──────────┬─────────────────────────────────┬───────────────────────┤
│ PROJECT  │  main.asm │ notes.txt   (tabs)  │  ▶ ⏸ ⏭ ⭮   EMULATOR  │
│ ▾ Source │                                 │  ┌─────────────────┐  │
│  main.asm│        EDITOR (central,         │  │  screen (48K)   │  │
│ ▾ Assets │        multi-view / split)      │  └─────────────────┘  │
│  hero.bmp│                                 ├───────────────────────┤
│  map.bin │                                 │  MEMORY CELLS (hex)   │
│  song.pt3│                                 │  [Memory|Output|Disasm]│
│          ├─────────────────────────────────┼───────────────────────┤
│          │  INSPECTOR (floatable)          │  REGISTERS / FLAGS    │
│          │                                 ├───────────────────────┤
│          │                                 │  MEMORY MAP  [Des|Dbg]│
├──────────┴─────────────────────────────────┴───────────────────────┤
│  50 fps | timer 100Hz | emulate 12ms/frame             (status bar) │
└────────────────────────────────────────────────────────────────────┘
```

Left = code work · Center = editor · Right = the running machine. See the live mockup for
proportions and interactions.

## Window & docking model

Built on stock Qt `QMainWindow` + `QDockWidget` — no third-party docking library
(evaluated the Qt Advanced Docking System / PyQtAds for full VS-style floating + auto-hide
pins, but the model below needs no extra dependency, and the core stays pure Python).

- **Editor = the central widget** — the fixed anchor everything docks around; being central
  it is inherently non-floatable. It is a **multi-view split area** (nested `QSplitter`s of
  tab groups) so files can sit side-by-side, VSCode-style (ship single-pane first, enable
  splitting once open/edit/save + Z80 highlighting + the breakpoint gutter work). Two views
  of one file share a single `QTextDocument` so edits and debugger markers stay in sync.
- **Project tree = a locked dock** on the left (movable/floatable features off) — always
  where you expect it.
- **Every other panel is a floatable `QDockWidget`** — emulator, memory cells (hex),
  registers/flags, memory map, inspector, output — so users can drag them, **tab them
  together** (drop one onto another), float them as windows, or hide them (each dock gives a
  View-menu toggle for free).
- **Layout persistence & presets:** `saveState()`/`restoreState()` serialise the whole
  arrangement; named presets give us the **Design** and **Debug** workspaces (Design
  foregrounds the memory map + inspector + assets; Debug foregrounds registers +
  disassembly + memory).
- **Emulator** keeps its own control strip (Run/Pause/Step/Reset) and scales responsively
  inside whatever dock size it's given.
- Trade-off accepted vs. full Visual Studio: no auto-hide "pushpin" (could adopt PyQtAds
  later if wanted).

---

## Load-bearing decision: memory is modeled as banks

The core is already paging-ready: `Memory` is four 16K slots, each backed by a swappable
`Bank`, with a `page(slot, bank)` hook (`zxemu_core/memory.py`). 48K wires it statically
(1 ROM + 3 RAM); 128K becomes a bank *pool* paged via port 0x7FFD. The UI must mirror this
**from day one**, even while we are 48K-only:

- **Model memory as banks (16K each), not a flat 64K array.** The 64K address space is a
  *projection* — whichever banks are currently paged into slots 0–3.
- The memory panel offers two views:
  - **"As the CPU sees it"** — the live 64K window (what PC/SP point at, what the ULA reads).
    The debugging default.
  - **"By bank"** — every bank (ROM0/1, RAM0–7), including ones *not* currently mapped in, so
    a paged-out bank is still inspectable and editable.
- **Assets and addresses are identified as `(bank, offset)`, not a bare 16-bit address**, so
  placement survives paging on 128K. On 48K this degenerates to the fixed map — nothing lost.
- The memory view surfaces the **current paging state** (the 0x7FFD value / which bank sits
  where).

The payoff: 128K becomes a *data* change, not a UI rewrite, and it costs essentially nothing
now because 48K is the trivial case.

---

## The memory view: two modes, one widget

A single bank-oriented widget with a **Design ⇄ Debug** toggle:

- **Design (before build)** — *where do assets live?* Drag-drop an asset onto a
  `(bank, offset)`, or hit **auto-locate** to place it in free space; this generates the
  `ORG` / `incbin` directives (or a memory manifest) the assembler consumes.
- **Debug (at run-time)** — *what is memory doing right now?* Live values, PC/SP markers,
  edit-a-byte, watch the screen bank change. The visual map is the overview you click into
  for hex detail.

---

## The debugger track

Cheap to build, because the core already exposes the pieces:

- `cpu.step()` runs exactly one instruction and returns its T-states → **single-step is
  nearly free**.
- `cpu.regs` holds every register (PC, SP, AF, BC/DE/HL + primes, IX, IY, I, R, IM) → a
  **registers/flags panel** is a read-out.
- `memory.read_byte` / `write_byte` → a **live, editable hex/memory view**.
- The **one real core addition** is a *debug run mode*: step instruction-by-instruction and
  check breakpoints (halt when `PC == bp`), instead of the fast atomic `run_frame()`. So the
  emulator controller carries two modes — **normal** (fast, frame-at-a-time) and **debug**
  (slower, can stop mid-frame).

v1 debugger minimum-viable = **registers + single-step + live memory view**; breakpoints,
disassembly, and watchpoints follow.

---

## Milestone 2 roadmap (phased)

- **Phase A — IDE shell layout** *(in progress)*: the dockable `QMainWindow` per the
  **Window & docking model** above — editor as central widget, Project as a locked left
  dock, and emulator / memory-cells / registers / memory-map / inspector / output as
  floatable docks; File menu; layout save/restore + Design/Debug presets. The frame pump is
  already extracted into an `EmulatorController` (run/pause/reset/step, `frame_ready` /
  `status_changed` signals), the emulator has its own control strip, and the fps readout
  moved to the status bar. *Remaining:* convert the current fixed splitter layout to the
  dock model and add the central editor host. UI-layer only — the core is untouched.
- **Editor track** *(new — supersedes "no built-in editor")*: an in-app multi-tab text
  editor for source and text assets, central and split-capable (see docking model). Grows
  Z80 syntax highlighting and a breakpoint gutter, and doubles as the debugger's source view
  (source ⇆ disassembly side by side, both tracking PC). Worth its own track; it changed the
  original "external editor only" plan because an in-app editor is far more useful for
  debugging.
- **Phase B — Project & asset system**: a project model + `.zxproj` on disk; the left tree
  bound to real source files and imported assets (bmp / binary / pt3 / beeper sfx); an
  Import action.
- **Phase C — External tools**: detect sjasmplus on `PATH` (overridable) for the build; a
  Settings dialog. "Open in external editor" (VS Code, detected) stays as an *option*
  alongside the built-in editor, not the only path.
- **Phase D — Build pipeline**: run sjasmplus, stream its output to the console panel, and on
  success load the emitted **snapshot** into the machine and run. Needs a new
  `zxemu_core/snapshot.py` — **.sna first**, with .szx / .tap / raw-binary as later formats
  (multiple build outputs are intended; snapshot is just the first).
- **Phase E — Visual memory management** *(the centerpiece)*: the bank-oriented memory map
  with drag-drop asset placement and auto-locate, feeding the Phase-D build. Depends on B+D.
- **Debugger track** (parallel to B–E): registers + step + memory view, then breakpoints /
  disassembly. Shares the memory widget with Phase E (its Debug mode).
- **Phase F — 128K machine**: a `Machine128` built on the paging abstraction (port 0x7FFD,
  AY sound, second ROM).

Rough order: A → B → C → D → E; the debugger and 128K slot in independently.

---

## Settled during layout review

- **Docking:** stock Qt docks; editor central, Project locked-left, everything else floatable
  (see Window & docking model). *(was open Q: docks vs splitter)*
- **Memory map form:** **bank-segmented columns** (one bar per slot, coloured by region, with
  PC/SP markers) — validated as genuinely useful in the mockup. Paired with a **hex memory
  cells** view for detail. *(was open Q: strip vs grid vs columns)*
- **Memory map placement:** its **own dock** on the right, under registers; the hex cells dock
  sits directly under the emulator. *(was open Q: tab vs dock)*
- **Editor:** in-app, central, multi-view/split — supersedes "external editor only".
- **Interface:** dark theme, High-DPI, Segoe UI + monospace console, adjustable UI scale.

## Open questions (to settle as we go)

1. Confirm **`(bank, offset)`** as the universal addressing convention everywhere.
2. Debugger v1 scope: ship "inspect + step" first and add breakpoints/disassembly later, or
   build the full debugger as one milestone?
3. How exactly the debug workflow is *used* day-to-day (still being explored).
4. Default proportions & which panels start visible vs. hidden in the Design/Debug presets.

---

## Appendix: original vision

> since this application is going to be "Unity" for ZX Spectrum. We need to think about UI
> and zxide project setup. I see that that in the middle will be our created previous
> zxemu_widget. on the left will project structure: source assets (imported asset?),
> sourcecode
>
> Beside this we have to have direct access to memory (since we have emulator intergrated it
> should be not so hard), memory management before compil. Literally locate assets in memory
> visaully. with drag and drop (but should have auto locate button).
>
> Imported assets could be bmp, binary, pt3 (for audio?), some asset for beeper sfx?
>
> We are going to use sjasmplus. and path to it could be taken from PATH environment.
> Default editor is VS (also should be findable via system)
>
> But can be changed to any other.
