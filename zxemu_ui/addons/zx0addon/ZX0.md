# ZX0 addon

Optional ZX0 decompression support for a zxide project. Nothing here is part of the
starter templates — a project only gets these files if you add the addon, so a project
that doesn't compress anything pays nothing for it.

## What's here

- `zx0.asm` — the runtime decompressor: spke's speed-optimised variant of Einar
  Saukas's ZX0 "Standard" decompressor, 191 bytes. Included verbatim; see its header
  for authorship and the zlib licence it ships under.

The compressor itself is a **host-side tool**, not part of this addon. Get `zx0` from
<https://github.com/einar-saukas/ZX0> and put it on your `PATH`.

## Using it

1. Compress your data on the host:

   ```
   zx0 mydata.bin          ->  mydata.bin.zx0
   ```

2. Include the routine somewhere in RAM. It carries no `org` of its own (the `org` in
   the original is commented out on purpose), so it lands wherever you place the
   include:

   ```asm
       include "zx0.asm"

   compressed_data:
       incbin "mydata.bin.zx0"
   ```

3. Point HL at the compressed data, DE at the destination, and call it:

   ```asm
       ld hl, compressed_data
       ld de, $c000
       call DecompressZX0
   ```

## Things to watch

- It uses **AF, AF', BC, DE, HL and IX**, so save anything you care about.
- It is **self-modifying**, so it must run from RAM — never place it in ROM, and don't
  assume it is re-entrant.
- On 128K, mind which bank is paged in at *both* the source and the destination when
  the call is made.
- Compression happens on the host, at build time. If you change `mydata.bin` you must
  re-run `zx0` — the assembler only sees the `.zx0` file.
