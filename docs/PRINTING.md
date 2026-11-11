# Printing, and how the print effect gets in

## The stock print path

All addresses are RAM addresses (flash = RAM - `0x01ffda00`).

1. `printer_jpeg` (`0x0205f6d0`, from a file) or `printer_jpeg_mem` (`0x0205f884`, from
   memory) decodes the photo's JPEG into an **8-bit grey picture, 255 = white**, scaled
   so one side is 384 dots (the print head is 384 dots, 48 mm, across 57 mm paper).
2. If its `print_mode` argument is 1, the firmware's own CLAHE (`0x0205f420`) runs on it.
3. `printer_print(buf, w, h, level, print_mode, x)` at `0x0205eefc` burns it.

There are three calls to the decoders: `0x0200bb20` and `0x0200d5b4` call
`printer_jpeg`, `0x0200bccc` calls `printer_jpeg_mem` (photo screen and gallery).

### Two layouts

- **`w == 384`: rows.** Line by line, each line 384 dots. A gallery reprint of a
  2304x1344 photo arrives as 384 x 224 (scaled exactly 6x; a test chart with 1-dot lines
  printed every line).
- **`h == 384`: columns.** The picture's long side runs along the paper; dot `k` of line
  `L` is `buf[(383 - k) * w + L]`. From the dot pattern on real prints, the print made
  right after taking a photo comes this way - it's the bigger, more detailed print.
- Anything else, `printer_print` refuses (returns 10).

### Real greys: 56 heat passes

`printer_print` doesn't dither. It makes 56 passes over each line; pass `k` heats every
dot whose value is `<= 4k` (thresholds 0, 4, ... 220). So 0 gets all 56 passes, 120 gets
26, 200 gets 6, and anything above 220 is never heated. Darkness comes from the number of
passes a dot gets.

How long each pass heats is set by:

- a battery reading (an ADC value bucketed into a base heat time; below a threshold the
  camera refuses to print), plus
- `level` = the **Print Density** setting (`SysCtrl.printer_level`, set by the settings
  menu): level 0 adds the most heat, each step up adds less.

So Print Density works on whatever picture reaches `printer_print` - including one the
print effect made.

On real paper (one camera, one roll, default density), a printed grey wedge measured as %
darker than the paper: input 0-60 all the same soft black (~50%), 75 -> 39%, 90 -> 33%,
105 -> 25%, 120 -> 15%, 135 -> 10%, 150 -> 5%, 165 and up -> white. That is why the grey
style uses just four tones: 255, 120, 80, 0. Big flat grey areas print a little lighter
than small ones (the driver shortens the strobe on busy lines).

Open question: with `print_mode == 1`, `printer_print` skips the lines and goes straight
to the final paper feed - while `printer_jpeg` runs its CLAHE only for `print_mode == 1`.
Which values the camera's own menus produce (`SysCtrl.printer_print_mode`, shown as
"printmode" on the photo and gallery screens) hasn't been explored. The prints in the
photos were made with the camera's default.

## How the effect hooks in

The obvious hook - patch the first instruction of `printer_print` in flash - is in
sector `0x61000`, which holds code the camera runs at power-on. A bad write there could
stop the camera before USB works. So the hook is put in place **in RAM, at print time**,
and the sectors written in flash hold no code that runs at power-on:

1. **The 3 call sites** (flash sectors `0xe000`, `0xf000`): `l.jal printer_jpeg` becomes
   `l.jal rq_wrap_jpeg` (and `_mem`).
2. **The wrappers** (`rq_tramp.S`, in the unreachable game-menu code, RAM `0x02015a00`,
   flash sector `0x18000`) save the arguments, and - only if the first word of
   `printer_print` in RAM is still the stock `l.sw -4(r1),r9` (`0xd7e14ffc`) - replace it
   with `l.j rq_tramp`, flush the data cache line, clear the instruction cache, then jump
   to the stock decoder as if nothing happened.
3. When the decoder calls `printer_print`, it lands in **`rq_tramp`**, which saves the
   arguments and calls the **loader stub** (`rq_stub.c`, same sector).
4. The stub reads the effect's 64-byte header from flash `0x380000` (magic `RQFX`), checks
   sizes, gets memory from the camera's own `malloc`, reads the effect in, checks its
   checksum, applies its relocations (32-bit words, HI16 / AHI16, LO16, SLO16), clears its
   BSS, flushes caches, and calls `fx_main(ctx, buf, w, h, level, mode)`. Then it frees the
   memory.
5. `rq_tramp` restores the arguments, does the stock first instruction itself
   (`l.sw -4(r1),r9`) and jumps to `printer_print + 4`. The camera prints the changed
   picture with its own driver, Print Density and all.

Anything unexpected - no effect in flash, a bad header or checksum, not enough memory, a
picture size the effect doesn't handle (`0xE1`), `printer_print` not stock - and the stub
steps aside and the photo prints normally.

Stock helpers the stub uses: `flash_read 0x020404f0(addr, dst, len)` (uses DMA above 15
bytes, rounds the length up to 16 and invalidates whole cache lines first - so read into
16-byte-aligned buffers), `malloc 0x0204195c(size, align)`, `free 0x0204179c`, data-cache
flush `0x0202da34(addr, len)`, instruction-cache invalidate `0x0202d9f0()`.

## The effect itself (`make/effect/rq_fx.c`)

Per print, seeded from the picture and a print counter:

1. Fat pixels: 4 x 2 dots (a 96-wide grid across the paper).
2. Auto levels (1%-99%), then CLAHE (3 x 2..5 tiles, clip 0.045).
3. Exposure metered on the middle of the picture, so a face lands on a mid tone.
4. Punch, then posterise: 5 levels drawn as 2x2 ordered-dither dots ("dots" style) or 4
   flat greys (`255, 120, 80, 0`, "grey" style) - 45 / 55%.
5. Two majority-filter passes (clean pixel art), then ink outlines on the strongest 4% of
   edges, on their darker side.
6. Glitch layer: 25% of prints none, else 1, 2, 3 or (rarely) 5 hits of mosh (dragged
   blocks), hair (a slipped line), stall (a smeared run), stutter (repeated block), tear
   (comb-like slip) or rot (speckle). Each hit avoids the middle 85% of the time.
7. Adventure-game bars (45%, rows layout only for now): "Score: N of M ... Sound:on" and a
   parser prompt (`>feed hamster_`), with the score going up 5 per print since switch-on.

Runs in about 13 million instructions per print; stack under 500 bytes; about 106 KB of
the camera's heap at most.

## Write your own effect

`fx_main` gets the decoded grey picture and changes it in place:

```c
typedef struct fx_ctx {
    u32 magic;                                /* 'RQFX' */
    void *(*malloc)(u32 size, u32 align);     /* the camera's heap */
    void (*free)(void *p);
    u32 seed;                                 /* per print */
    u32 count;                                /* prints since power on */
    u32 force_style, force_chrome;            /* tests only */
} fx_ctx;

u32 fx_main(fx_ctx *c, u8 *buf, int w, int h, int level, int mode);
```

Handle both layouts (the rows one is easiest to think in; `rq_fx.c` turns columns into rows
and back). Return any small number - it's kept in RAM for debugging.

The toolchain trap: Ubuntu's `gcc-or1k-elf` builds **big-endian code with branch delay
slots**; this CPU is **little-endian without delay slots**. `make/effect/build_fx.py`
handles it:

- `-fno-delayed-branch`: the compiler fills every delay slot with `l.nop`, which is
  harmless on a CPU that has none.
- No `-fPIC` (its GOT setup relies on delay slots); the stub relocates the effect instead,
  and the build checks those relocations against the linker's own output at a second
  address.
- Instruction words are byte-swapped after linking. Constant data must be **byte arrays
  only** (a u32 table would come out byte-swapped) - the build refuses anything else, and
  `-fno-store-merging` stops gcc from combining byte stores into word stores.
- Only instructions the stock firmware itself uses are allowed (the build checks every
  opcode). Notably no `l.muli`: `opq()` in the source hides constants from the optimiser.

Testing, from the cheapest up:

1. `host_fx.c` / `host_run.py`: the same C on your PC, on any photo.
2. `fuzz_fx.c`: thousands of random sizes and pictures under ASan + UBSan.
3. `emu.py` + `test_fx_emu.py BUILD_DIR PHOTO...`: a strict little-endian, no-delay-slot
   OpenRISC emulator runs the real patched firmware bytes from the call site through the
   wrapper, stub and effect, with the camera's helpers modelled (DMA rounding included),
   every memory access checked, and the printed dots compared with the PC build, dot for
   dot. `test_fx_emu_edge.py` covers the step-aside cases.

Then `build_fx.py BACKUP.bin OUT` -> `make_pack.py` (see [MAKING_MODS.md](MAKING_MODS.md)).
