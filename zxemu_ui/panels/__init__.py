"""Panels: the dockable views that show what the machine is doing.

Each is a self-contained ``QWidget`` that reads a ``Machine`` and renders some part
of it. They share one convention and almost nothing else:

    view.machine                 the machine to read (rebound when the model changes)
    view.refresh(frame_count)    called on every emulated frame; returns early when
                                 the panel is hidden, so a closed panel costs nothing
    view.set_mono_scale(scale)   follow the IDE's interface-scale setting

That contract is the whole reason ``MainWindow`` can treat them uniformly -- connect
one signal to all of them, rebind them all when the machine is swapped -- without
knowing what any of them draws.

    emulator_view.py    The screen itself: bitmap + attributes + border + FLASH, and
                        PC keys mapped onto the Spectrum's 8x5 matrix.
    emulator_panel.py   The screen plus its control strip (run / pause / step / reset).
    registers_view.py   Registers and flags, a T-state read-out, and click-to-edit.
    memory_cells_view.py  Hex dump, with a Poke field to write bytes back.
    memory_map_view.py  Bank-oriented overview with PC/SP markers and 128K paging.
    disassembly_view.py Code around PC, decoded, with ROM and project labels.
    call_stack_view.py  The inferred chain of callers.
    analysis_view.py    Results of whole-program queries (search, xrefs, coverage).
    inspector_view.py   Details of a selected asset (a stub for now).

The debug panels look at the same memory through different lenses on purpose: the
hex dump says what the bytes *are*, the disassembly says what they *mean*, the map
says where they *live*, and the call stack says how you *got* there. Which one
answers your question depends entirely on the question.
"""
