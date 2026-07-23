; main.asm -- 48K zxide starter project
;
; A tiny but visible demo: it sets a red border and paints a striped colour
; screen, so Build + Run clearly shows *your* program running rather than the
; ROM boot screen. Replace the body with your own code.
;
; sjasmplus assembles this file; the SAVESNA directive at the end writes the
; snapshot the emulator loads (sjasmplus has no --sna flag -- output is directive
; driven). DEVICE selects the target machine.

    device zxspectrum48

    include "zxspectrum.asm"        ; screen / port / system-variable equates
    include "assets_generated.asm"  ; imported assets -- see the Design-mode memory map

    org $8000

start:
    di
    ld sp, $7fff

    ld a, 2                        ; border: red
    out (ULA_PORT), a

    ; fill the 6144-byte bitmap with a vertical-stripe pattern
    ld hl, DISPLAY_PIXELS
    ld (hl), $aa
    ld de, DISPLAY_PIXELS + 1
    ld bc, 6144 - 1
    ldir

    ; colour the 768-byte attribute area: bright white ink on blue paper
    ld hl, DISPLAY_ATTRS
    ld (hl), $4f
    ld de, DISPLAY_ATTRS + 1
    ld bc, 768 - 1
    ldir

loop:
    jr loop                       ; your program continues from here

    savesna "main.sna", start
