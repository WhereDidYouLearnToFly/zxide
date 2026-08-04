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
                        screenshot / record), and the fullscreen toggle. The record pair
                        only asks; ``zxemu_ui/recorder.py`` does the capturing.
    fullscreen_stage.py The bare window that borrows the emulator for the whole display
                        (Alt+Enter in, Esc out) -- it lends the *same* live widget rather
                        than building a second renderer, so nothing is disturbed.
    registers_view.py   Registers and flags, a T-state read-out, and click-to-edit.
    memory_cells_view.py  Hex dump, with a Poke field to write bytes back.
    memory_plan_window.py
                        Where everything lands, as a maximisable *window* rather than a
                        dock, and deliberately **not** to scale: one uniform row per
                        block carrying its name, start-end and size as text, with the
                        free space between them spelled out, and a column per bank.
                        There was a to-scale dock version of this first; it was dropped
                        because neither of its two ideas survived contact with a real
                        project. Proportional drawing makes a 43-byte routine two pixels
                        of a 16K column -- unreadable and unclickable, which is most of
                        what a program is made of. And its columns were *slots*, so a
                        128K project spread across more than four banks was half
                        invisible, when where bytes are assembled has nothing to do with
                        what the CPU can see this instant.
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
    sprite_editor_view.py  Draw a sprite in the IDE, in real ZX colours. One tool, no
                        modes: drawing a pixel also claims its 8x8 cell for the selected
                        ink/paper, so the two-colours-per-cell limit is a consequence of
                        drawing rather than a rule to remember. The left button toggles,
                        which is what makes erasing free of colour-switching. Pixel-only
                        sprite formats have no attributes, so it drops to black and white
                        for those.
    beeper_sfx_editor_view.py  Build a beeper effect as a bar chart of frequency over
                        time -- each bar's height is its tone, its width is how long
                        that tone lasts -- because an effect is a shape, and nobody
                        hears a shape by reading a column of periods and frame counts.
                        Drag up for higher, sideways for longer; there are no settings,
                        because length is what the drag is for. The frequency axis is
                        logarithmic, or the whole low end where thuds and rumbles live
                        would be a sliver.
    ay_player_view.py   Play a music file and watch the chip while it does. Floating by
                        default, because it is something you pop out beside the IDE for
                        as long as a tune lasts. The display is three channel meters and
                        nothing else -- not from modesty but because these formats are
                        Z80 programs rather than note lists (see zxemu_core/sound), so
                        pattern and row genuinely are not knowable; the chip's own state
                        is. Playback runs on its own private machine, so auditioning a
                        tune never disturbs the emulator you are debugging with.
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
