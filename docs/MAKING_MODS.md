# Making your own mods

Everything here runs on Linux, macOS or Windows (WSL is easiest for the effect). You need
your own stock backup from `install/3_BACKUP.bat` - every tool checks it against the
tested firmware first.

Python packages: `numpy`, `pillow`, `scipy` (sounds, frames, screens). For the print
effect: `gcc-or1k-elf` and `binutils-or1k-elf` (Ubuntu/Debian: `sudo apt install
gcc-or1k-elf binutils-or1k-elf`; the build was done with gcc 13.2).

The flow is always the same:

```
your backup  ->  a builder makes a modded 4 MiB image  ->  make_pack.py  ->  NAME.rqp + NAME.json
```

and the pack goes into `install/packs/`. Packs never contain the camera's firmware, so
you can share them.

## 0. Look at what's there

```
python make/extract_resources.py BACKUP.bin res
```

Every picture and sound the camera has, as files, plus `res/resources.json` (where each
one lives, its size, which sectors it touches). [FLASH_MAP.md](FLASH_MAP.md) has the
table with what we know each one is. Resources never move or change size: your new
content has to fit the old slot.

## 1. Sounds

Seven slots. Lengths are exact (shorter is padded with silence, longer is cut):

| file name | res | plays | format | length |
|---|---|---|---|---|
| `slot01_click_b.wav` | 28 | a button click | 22.05 kHz stereo | 838 frames (0.038 s) |
| `slot02_click_d.wav` | 45 | a button click | 16 kHz mono | 944 frames (0.059 s) |
| `slot03_click_a.wav` | 46 | a button click | 16 kHz mono | 1297 frames (0.081 s) |
| `slot04_click_c.wav` | 47 | a button click | 16 kHz mono | 1009 frames (0.063 s) |
| `slot05_poweroff.wav` | 48 | switching off | 16 kHz mono | 29222 frames (1.83 s) |
| `slot06_poweron.wav` | 49 | switching on | 16 kHz mono | 25890 frames (1.62 s) |
| `slot07_shutter.wav` | 50 | taking a photo | 16 kHz mono | 6626 frames (0.41 s) |

All 16-bit PCM. The speaker is tiny: nothing above 8 kHz exists at 16 kHz, and not much
below ~400-500 Hz is audible.

```
python make/sounds/make_sounds.py my_jingle.wav 06      # converts, trims/pads, normalises
                                                        # -> out/slot06.wav (+ a speaker preview)
# put all seven, named exactly as above, in one folder (start from make/sounds/wavs/)
python make/sounds/rq_sound_image.py BACKUP.bin MY_SOUNDS OUT.bin all
python make/make_pack.py BACKUP.bin OUT.bin install/packs/my-sounds --title "MY SOUNDS" \
    --windows 0x1f1-0x1f3,0x228-0x248 \
    --last-install 0x237000,0x238000,0x239000,0x23a000,0x23b000,0x23c000,0x23d000,0x23e000,0x23f000,0x240000,0x241000,0x242000,0x243000,0x244000 \
    --last-undo    0x237000,0x238000,0x239000,0x23a000,0x23b000,0x23c000,0x23d000,0x23e000,0x23f000,0x240000,0x241000,0x242000,0x243000,0x244000
```

(The `--last-*` sectors hold the power-on sound; writing them last keeps the time it is
half-written as short as possible.) The camera's own WAV headers are kept; only the audio
bytes change.

## 2. Photo frames

21 frames, res04-res24, each a 1280x720 JPEG. **Pure black = the photo shows through**;
everything else is drawn over the photo. Keep drawn colours at luma 64 or more (the stock
frames' darkest visible colour is grey 49). Chunky shapes and text survive best: the print
is 384 dots across.

```
python make/screens/build_frames.py BACKUP.bin OUT.bin                  # the Receipt Quest designs (frames.py)
python make/screens/build_frames.py BACKUP.bin OUT.bin MY_FRAMES        # yours: res04.png .. res24.png
python make/make_pack.py BACKUP.bin OUT.bin install/packs/my-frames --title "MY FRAMES" --windows 0xb7-0x1dd
```

## 3. Screens

What Receipt Quest changes (formats in [FLASH_MAP.md](FLASH_MAP.md)):

| res | what | format |
|---|---|---|
| 39 | main menu background, with the 5 unselected icons in it | JPEG 320x240 |
| 40-44 | the 5 selected icons, drawn over res39 at fixed spots | BMP 100x90, 24-bit, bottom-up |
| 64 | sprite atlas; sprite #1 is the highlighted bar in settings | uses palette res65 (RGB565 + 5-bit alpha) |
| 67 / 68 | switch-off / switch-on screen | JPEG 320x240 |
| 71 | settings background (the firmware draws the white text, icons and bar on it) | JPEG 320x240 |
| 78 | USB screen | JPEG 320x240 |

`make/screens/menus.py` is the Receipt Quest look (degraded VHS tape) - read it as an
example rather than a library.
`build_screens.py` puts it all in:

```
RQ_STOCK=res python make/screens/build_screens.py BACKUP.bin OUTDIR      # res = from extract_resources.py
python make/make_pack.py BACKUP.bin OUTDIR/target_screens.bin install/packs/my-menus --splice \
    --title "MY MENUS" --windows 0x201-0x228,0x254-0x257,0x2d1-0x2da
python make/make_pack.py BACKUP.bin OUTDIR/target_screens.bin install/packs/my-startup --splice \
    --title "MY START-UP" --windows 0x295-0x2aa,0x2f5-0x2fd --requires my-menus \
    --last-install 0x29f000,0x2a0000,0x2a1000,0x2a2000,0x2a3000,0x2a4000,0x2a5000,0x2a6000,0x2a7000,0x2a8000,0x2a9000 \
    --last-undo    0x29f000,0x2a0000,0x2a1000,0x2a2000,0x2a3000,0x2a4000,0x2a5000,0x2a6000,0x2a7000,0x2a8000,0x2a9000
```

Why two packs: the start-up screen is the first thing the camera shows. Installing the
menus first proves your camera displays the new pictures before its start-up screen is
touched. Sector `0x228000` is shared by the end of res44 and the start of the sounds, so
the screens builder leaves the end of res44 exactly as it is.

## 4. A print effect

See [PRINTING.md](PRINTING.md) for the API and the toolchain traps. Then:

```
cd make/effect
python3 gen_tables.py                       # only if you change the exposure table or font
python3 host_run.py photo.jpg 4             # try the C on your PC first: 4 prints' worth of PNGs
python3 build_fx.py BACKUP.bin OUT          # -> OUT/fx_app_image.bin (+ fx_build.json)
python3 test_fx_emu.py OUT photo1.jpg photo2.jpg ...   # camera build == PC build, dot for dot
python3 test_fx_emu_edge.py OUT
python3 ../make_pack.py BACKUP.bin OUT/fx_app_image.bin ../../install/packs/my-effect \
    --title "MY EFFECT" --windows 0xe-0x10,0x18-0x19,0x380-0x384 \
    --last-install 0xe000,0xf000 --first-undo 0xe000,0xf000
```

The effect lives in flash `0x380000`-`0x383fff` (16 KiB; the camera never uses that area).
For a bigger effect, widen that window - the writer helper is built from the pack's
windows.

## 5. Check, share

1. Put `NAME.rqp` and `NAME.json` in `install/packs/`.
2. Run the offline rehearsal - it installs and undoes every pack in the folder on a
   simulated camera, including interrupted writes:
   `python install/tests/test_install_offline.py BACKUP.bin /tmp/rq`
3. Copy an `INSTALL_....bat` and `UNDO_....bat`, change the pack name in the last command.
4. `LIST_MODS.bat` should show it, and "fits your backup".
5. Open a pull request. Two packs may not change the same sector; a pack that replaces
   another (say, different sounds) is fine, as long as people undo one before installing
   the other.

`make_pack.py` refuses windows that include the boot sectors, the power-on code sector
`0x61000`, the resource table or the settings, and checks that the pack rebuilds your image
exactly.

## The PC converter (no flashing)

`make/pc-converter/` is where this project started: plug the camera in, run
`MAKE_PRINTS.bat`, and every new photo on the card is backed up to your PC and replaced by
a Receipt Quest version (same file name), which you then print from the gallery. It works
on any camera that prints the photo stored on the card - no firmware involved. Run
`SETUP.bat` once (it installs numpy, scipy, scikit-image, Pillow and OpenCV into a local
`.venv`), and see `settings.txt`.
