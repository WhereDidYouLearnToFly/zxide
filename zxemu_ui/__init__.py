"""zxemu_ui -- the PyQt5 user-interface layer.

The emulator core (``zxemu_core``) is deliberately UI-agnostic: it knows how to
*be* a Spectrum, but nothing about windows, pixels drawn on your screen, or your
PC keyboard. This package is the other half -- it takes a running core and makes
it visible and interactive:

    emulator_view.py  A QWidget that, each frame, (a) reads the core's screen
                      memory and paints it (bitmap + colour attributes + border
                      + FLASH), and (b) translates your PC key presses into the
                      Spectrum's key-matrix presses.
    controller.py     Drives the machine in real time (the frame pump) and offers
                      the IDE's run / pause / reset / step controls, talking to the
                      rest of the UI purely through Qt signals.
    emulator_panel.py Groups the emulator view with its own control strip (Run /
                      Pause / Step / Reset on top) and fits the screen to its dock.
    editor.py         The central, multi-tab code/text editor (the dock anchor).
    z80_highlighter.py    Syntax colouring for Z80 assembly in the editor.
    project.py        A folder-based project + its zxide.json manifest (+ scaffolding).
    settings.py       App settings (auto-created; sjasmplus auto-detected).
    settings_dialog.py    Dialog to override the build configuration.
    builder.py        Runs sjasmplus on a project and reports the result.
    registers_view.py     Live read-out of the Z80 register file + flags.
    memory_cells_view.py  Live hex dump of memory (address + hex + ASCII).
    memory_map_view.py    Visual, bank-oriented overview of memory with PC/SP markers.
    inspector_view.py     Details of the selected asset/region (stub for now).
    main_window.py    The IDE shell: a Visual-Studio-style dock layout with the
                      editor central and the emulator + debug panels as docks.
    theme.py          Applies the dark Fusion palette + fonts used across the IDE.

Keeping the UI separate from the core is what lets the same emulator run
headless in tests, and lets the view be embedded as a panel inside the larger IDE
window -- the way a game viewport sits inside an editor. The top-level ``main.py``
is now just a composition root that wires these three together.
"""
