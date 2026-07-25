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

Watching the machine:

    emulator_view.py    The screen itself: bitmap + attributes + border + FLASH, and
                        PC keys mapped onto the Spectrum's 8x5 matrix.
    emulator_panel.py   The screen plus its control strip (run / pause / step / reset /
                        screenshot), and the fullscreen toggle.
    fullscreen_stage.py The bare window that borrows the emulator for the whole display
                        (Alt+Enter in, Esc out) -- it lends the *same* live widget rather
                        than building a second renderer, so nothing is disturbed.
    registers_view.py   Registers and flags, a T-state read-out, and click-to-edit.
    memory_cells_view.py  Hex dump, with a Poke field to write bytes back.
    memory_map_view.py  Bank-oriented overview with PC/SP markers and 128K paging --
                        and, in Design mode, drag-and-drop asset placement.
    disassembly_view.py Code around PC, decoded, with ROM and project labels.
    call_stack_view.py  The inferred chain of callers.
    analysis_view.py    Results of whole-program queries (search, xrefs, coverage).
    disk_view.py        What is in the drives and what is on it -- the catalogue read
                        straight from the image, so it still answers when the machine
                        is paused or a load has just gone wrong and TR-DOS's own CAT
                        is out of reach. Also the only place the "modified, unsaved"
                        state of a disk is visible.

Working on your own material:

    inspector_view.py   What a selected asset is and what it will look like: rendered
                        previews per kind, plus playback for beeper SFX.
    sprite_editor_view.py  Draw a sprite in the IDE, in real ZX colours, where every
                        paint action reclaims its 8x8 cell's attribute -- so the
                        two-colours-per-cell hardware limit is a consequence of the
                        tool rather than a rule you could break.
    beeper_sfx_editor_view.py  Build a beeper effect as rows of Hz + frames, with a
                        Play button, because a raw T-state period is not a format
                        anyone can hand-author.
    output_console.py   The Output panel: build log and search results, where result
                        lines are clickable links to a file and line.

The debug panels look at the same memory through different lenses on purpose: the
hex dump says what the bytes *are*, the disassembly says what they *mean*, the map
says where they *live*, and the call stack says how you *got* there. Which one
answers your question depends entirely on the question.

The editors break the ``machine`` / ``refresh`` contract above, and should: they are
about files on disk, not about the running machine, so they take a project and an
asset instead. They also all **autosave straight through** on every edit -- the
convention the whole asset system follows.
"""
