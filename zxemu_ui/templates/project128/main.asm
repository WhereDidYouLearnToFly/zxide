; main.asm -- 128K zxide starter project
;
; A visible + audible 128K demo. Beyond painting the screen it does two things the
; 48K cannot, so you can see the IDE's 128K features working:
;
;   1. MEMORY PAGING. Port $7FFD swaps a RAM bank into the top 16K ($C000-$FFFF).
;      We page RAM bank 3 in and drop a marker byte there -- watch the memory-map
;      pane's slot 3 change to "RAM3" and the marker appear at $C000 in the hex view.
;   2. AY SOUND. The 128K's AY-3-8912 chip plays a steady tone on channel A, mixed
;      into the same output as the beeper.
;
; sjasmplus assembles this; DEVICE selects the 128K, so the SAVESNA at the end writes
; a 128K-format snapshot (131103 bytes) the emulator loads. Replace the body with your own.

    device zxspectrum128

    include "zxspectrum.asm"        ; screen / port / paging / AY equates

    org $8000

start:
    di
    ld sp, $7fff

    ld a, 5                        ; border: cyan
    out (ULA_PORT), a

    ; fill the 6144-byte bitmap with a diagonal-ish pattern
    ld hl, DISPLAY_PIXELS
    ld (hl), $3c
    ld de, DISPLAY_PIXELS + 1
    ld bc, 6144 - 1
    ldir

    ; colour the attributes: bright yellow ink on magenta paper
    ld hl, DISPLAY_ATTRS
    ld (hl), $63
    ld de, DISPLAY_ATTRS + 1
    ld bc, 768 - 1
    ldir

    ; --- page RAM bank 3 into $C000 and leave a marker there ---
    ld bc, BANK_PORT
    ld a, %00000011               ; bits 0-2 = 3 -> RAM3 at $C000 (ROM0, normal screen, unlocked)
    out (c), a
    ld a, $de                     ; a recognisable marker byte...
    ld ($c000), a                 ; ...now living in RAM bank 3

    ; --- start an AY tone on channel A (~440 Hz) ---
    call ay_init

loop:
    jr loop                       ; your program continues from here

; Program the AY: tone period on channel A, enable only tone A, set its volume.
ay_init:
    ld a, 0                       ; R0: channel A tone period, fine byte
    ld e, $fc
    call ay_out
    ld a, 1                       ; R1: channel A tone period, coarse byte (TP=$00FC ~ 440 Hz)
    ld e, $00
    call ay_out
    ld a, 7                       ; R7: mixer -- 0 = enabled; enable tone A only, no noise
    ld e, %00111110
    call ay_out
    ld a, 8                       ; R8: channel A volume (0-15, bit 4 = follow envelope)
    ld e, $0d
    call ay_out
    ret

; Write E into AY register A:  select via $FFFD, then write via $BFFD.
ay_out:
    ld bc, AY_SELECT
    out (c), a                    ; B holds the high byte, so this selects register A
    ld bc, AY_WRITE
    out (c), e                    ; write the value
    ret

    savesna "main.sna", start
