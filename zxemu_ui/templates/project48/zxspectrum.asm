; zxspectrum.asm -- common ZX Spectrum 48K addresses and equates.
;
; A convenience header you include from your sources (see main.asm). These are the
; standard, well-known hardware/ROM constants; extend it with the routines and
; system variables your program uses.

; --- display ---------------------------------------------------------------
DISPLAY_PIXELS      equ $4000       ; 6144-byte bitmap (the screen)
DISPLAY_ATTRS       equ $5800       ; 768-byte colour attribute area

; --- ports -----------------------------------------------------------------
ULA_PORT            equ $fe         ; out: border/beeper/mic   in: keyboard/EAR

; --- system variables ------------------------------------------------------
LAST_K              equ 23560       ; last key pressed (ASCII), $5C08
FRAMES              equ 23672       ; 3-byte frame counter, +1 every 1/50s, $5C78

; --- ROM routines ----------------------------------------------------------
ROM_CLS             equ $0daf       ; clear the screen
