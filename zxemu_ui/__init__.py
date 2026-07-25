"""zxemu_ui -- the PyQt5 user-interface layer.

The emulator core (``zxemu_core``) is deliberately UI-agnostic: it knows how to
*be* a Spectrum, but nothing about windows, pixels drawn on your screen, or your
PC keyboard. This package is the other half -- it takes a running core and makes it
visible and interactive.

The shell, at the top level:

    main_window.py    The IDE itself: a Visual-Studio-style dock layout with the
                      editor central and everything else as dockable panels, and the
                      wiring that connects them. **Start here.**
    menu_builder.py   The menu bar, declared as data -- a list of items per menu, each
                      with its label, shortcut, tooltip and real handler. Read this to
                      see what the IDE can do, in one page.
    debug_session.py  What the debugger knows and what should make it stop: the source
                      map from the last build, breakpoints and their conditions, and
                      the watched addresses and ports. One object rather than six
                      attributes scattered through the window.
    media.py          Somebody else's program: which loader a file needs (.sna/.z80 vs
                      .tap/.tzx) and what the log should say about it. No Qt.
    controller.py     Drives the machine in real time (the frame pump) and offers
                      run / pause / reset / step / run-to controls, breakpoints and
                      watchpoints -- talking to the rest of the UI purely through Qt
                      signals, so nothing else needs to know how timing works.
    editor.py         The central multi-tab code editor, with a breakpoint gutter
                      and an execution-line marker.
    z80_highlighter.py    Syntax colouring for Z80 assembly.
    machine_factory.py    Builds the right machine (48K or 128K) for a model string.
    audio_output.py   Plays the core's PCM through the system sound device (a thin
                      QtMultimedia sink that fails quiet when there isn't one).
    layout_store.py   Saves and restores the dock layout as readable JSON.
    theme.py          The dark Fusion palette and the fonts used throughout.
    asset_icons.py    Small drawn icons for the asset kinds in the project tree.
    system_open.py    Hands a path to the desktop's own file manager ("Show in
                      Explorer"), one command per platform.

And two groups, each with its own overview:

    panels/     The dockable views -- screen, registers, memory, disassembly, call
                stack, analysis, Output -- plus the asset editors (sprite, beeper SFX)
                and the Inspector. The machine-watching ones share a small contract
                (``machine`` / ``refresh`` / ``set_mono_scale``), which is what lets
                MainWindow treat them all alike.
    workspace/  Your project rather than the machine: the folder and its manifest,
                app settings, the sjasmplus build, asset codegen, project-wide search,
                and the SLD map that ties source lines to addresses.

Keeping the UI separate from the core is what lets the same emulator run headless in
tests, and lets the screen be embedded as one panel inside a larger window -- the way
a game viewport sits inside an editor. The top-level ``main.py`` is just a
composition root that wires these pieces together.
"""
