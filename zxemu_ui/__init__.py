"""zxemu_ui -- the PyQt5 user-interface layer.

The emulator core (``zxemu_core``) is deliberately UI-agnostic: it knows how to
*be* a Spectrum, but nothing about windows, pixels drawn on your screen, or your
PC keyboard. This package is the other half -- it takes a running core and makes
it visible and interactive:

    emulator_view.py  A QWidget that, each frame, (a) reads the core's screen
                      memory and paints it (bitmap + colour attributes + border
                      + FLASH), and (b) translates your PC key presses into the
                      Spectrum's key-matrix presses.

Keeping the UI separate from the core is what lets the same emulator run
headless in tests, and lets this widget be embedded as a panel inside a larger
IDE window later -- the way a game viewport sits inside an editor. The frame
loop that actually drives the machine lives in the top-level ``main.py``.
"""
