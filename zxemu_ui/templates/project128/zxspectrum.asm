; zxspectrum.asm -- equates for a 128K zxide project (screen, ports, system vars).
;
; Shared, directive-free include: no DEVICE here, so it can sit alongside the
; 128K main.asm without dictating the target machine.

DISPLAY_PIXELS  equ $4000        ; 6144-byte bitmap (RAM bank 5, the normal screen)
DISPLAY_ATTRS   equ $5800        ; 768-byte attribute area

ULA_PORT        equ $fe          ; border (bits 0-2) / speaker (bit 4) / keyboard

; 128K-only hardware.
BANK_PORT       equ $7ffd        ; memory paging: bits 0-2 RAM->$C000, 3 screen, 4 ROM, 5 lock
AY_SELECT       equ $fffd        ; choose an AY register (also reads it back)
AY_WRITE        equ $bffd        ; write the chosen AY register

; System variables / ROM entry points.
LAST_K          equ 23560
FRAMES          equ 23672
ROM_CLS         equ $0daf
