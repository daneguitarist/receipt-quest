# Flash map (AX3291A, firmware 20240822_V1.9)

The flash is a GD25Q32: 4 MiB, 4 KiB erase sectors, 256-byte pages (JEDEC `c8 40 16`).

| flash | what | written by Receipt Quest? |
|---|---|---|
| `0x000000`-`0x002fff` | boot header (`BLDR` at offset 4) and boot stub | never |
| `0x002600`-`0x0a99ff` | the application: `0x53a` x 512 bytes, loaded to RAM `0x02000000` (RAM = flash + `0x01ffda00`) | 3 sectors, by the print effect |
| `0x061000` | holds code the camera runs at power-on (nvfs init `0x0205f9a8`, printer init `0x0205ebf8`) | **never** |
| `0x0b1600` | the resource table (sector `0xb1`) | **never** |
| `0x0b1880`-`0x2fdfff` | the 80 resources: pictures, sounds, sprites | sounds, frames, screens |
| `0x2ff000` | the camera's settings (nvfs); differs from camera to camera | **never** |
| `0x300000`-`0x3fffff` | erased, unused by the firmware | `0x380000`-`0x383fff`: the print effect |

## The application header and boot

- The header points at the application: start sector `0x13` (flash `0x2600`), `0x53a`
  sectors of 512 bytes, load address `0x02000000`.
- The boot ROM's CRC check of the application is switched off in this build (header byte
  `0x39` bit 7 clear, placeholder CRC `0x01234567`), so modified application sectors boot.
  This was confirmed by tracing the ROM, and by the penguin-camera project booting
  modified application code on the sister camera.
- At power-on: `0x02000640` -> `0x0200013c`, which runs nvfs init (`0x0205f9a8`) and printer
  init (`0x0205ebf8`) - both in flash sector `0x61000` - **before** the SD-card updater
  (`0x02002840`) gets a chance. A broken `0x61000` would stop the camera before anything
  could repair it, so no tool here can write it.
- The SD-card updater flashes `DestBin.bin` from the card's root on start-up. Never put
  that file on the card unless you mean it: it rewrites the whole flash.
- When the camera boots with USB connected it opens its "usb device" window (window 10).

Windows (screens) in the firmware, for reference: 1 power off, 2 video, 3 photo, 4
playback, 5 audio player, 6 main menu, 7 game menu (unreachable), 8 game, 9 settings,
10 usb device. `open_window` is at `0x02008948`. The game menu's code (RAM `0x0201580c`-
`0x0201657c`, flash sector `0x18000`) is never reached from any other window, which is why
the print effect can borrow it.

## The resource table

The u32 at flash `0x18`, times 512, is the table's address (`0xb1600`). It is a list of
`(offset, size)` u32 pairs, relative to the table; the first offset / 8 is the number of
entries (80). `make/extract_resources.py BACKUP.bin OUT` writes every resource to a file
(and a PNG of every picture) plus `resources.json`.

Mods here never move a resource or change its size: new content goes into the same slot
(JPEGs are encoded to fit and zero-padded; BMPs keep the stock header; WAVs keep the stock
44-byte header and length). That way the table never has to be rewritten.

Pictures are baseline JPEG (4:2:0) or 24-bit bottom-up BMP. Sounds are 16-bit PCM WAV.
Anything in bold is confirmed on the real camera; the rest is unexplored - have a look and
tell us.

| res | flash | bytes | kind | size / format | what |
|---|---|---|---|---|---|
| 00 | `0xb1880` | 0 | bin |  |  |
| 01 | `0xb1880` | 9562 | jpg | 320x240 |  |
| 02 | `0xb3dda` | 8263 | jpg | 320x240 |  |
| 03 | `0xb5e21` | 6958 | jpg | 216x136 |  |
| 04 | `0xb794f` | 45048 | jpg | 1280x720 | **photo frame 1** (pure black = photo shows through) |
| 05 | `0xc2947` | 38525 | jpg | 1280x720 | **photo frame 2** (pure black = photo shows through) |
| 06 | `0xcbfc4` | 47145 | jpg | 1280x720 | **photo frame 3** (pure black = photo shows through) |
| 07 | `0xd77ed` | 80100 | jpg | 1280x720 | **photo frame 4** (pure black = photo shows through) |
| 08 | `0xeb0d1` | 47109 | jpg | 1280x720 | **photo frame 5** (pure black = photo shows through) |
| 09 | `0xf68d6` | 68381 | jpg | 1280x720 | **photo frame 6** (pure black = photo shows through) |
| 10 | `0x1073f3` | 51199 | jpg | 1280x720 | **photo frame 7** (pure black = photo shows through) |
| 11 | `0x113bf2` | 66631 | jpg | 1280x720 | **photo frame 8** (pure black = photo shows through) |
| 12 | `0x124039` | 66710 | jpg | 1280x720 | **photo frame 9** (pure black = photo shows through) |
| 13 | `0x1344cf` | 63562 | jpg | 1280x720 | **photo frame 10** (pure black = photo shows through) |
| 14 | `0x143d19` | 56087 | jpg | 1280x720 | **photo frame 11** (pure black = photo shows through) |
| 15 | `0x151830` | 59169 | jpg | 1280x720 | **photo frame 12** (pure black = photo shows through) |
| 16 | `0x15ff51` | 39465 | jpg | 1280x720 | **photo frame 13** (pure black = photo shows through) |
| 17 | `0x16997a` | 42339 | jpg | 1280x720 | **photo frame 14** (pure black = photo shows through) |
| 18 | `0x173edd` | 48549 | jpg | 1280x720 | **photo frame 15** (pure black = photo shows through) |
| 19 | `0x17fc82` | 36931 | jpg | 1280x720 | **photo frame 16** (pure black = photo shows through) |
| 20 | `0x188cc5` | 48845 | jpg | 1280x720 | **photo frame 17** (pure black = photo shows through) |
| 21 | `0x194b92` | 36631 | jpg | 1280x720 | **photo frame 18** (pure black = photo shows through) |
| 22 | `0x19daa9` | 45787 | jpg | 1280x720 | **photo frame 19** (pure black = photo shows through) |
| 23 | `0x1a8d84` | 41421 | jpg | 1280x720 | **photo frame 20** (pure black = photo shows through) |
| 24 | `0x1b2f51` | 171273 | jpg | 1280x720 | **photo frame 21** (pure black = photo shows through) |
| 25 | `0x1dcc5a` | 51785 | jpg | 320x240 |  |
| 26 | `0x1e96a3` | 16192 | jpg | 320x240 |  |
| 27 | `0x1ed5e3` | 18536 | bin |  |  |
| 28 | `0x1f1e4b` | 3396 | wav | 22050 Hz, stereo, 0.038 s | button click (22.05 kHz stereo) |
| 29 | `0x1f2b8f` | 432 | bin |  |  |
| 30 | `0x1f2d3f` | 3300 | bin |  |  |
| 31 | `0x1f3a23` | 1176 | bin |  |  |
| 32 | `0x1f3ebb` | 8100 | bin |  |  |
| 33 | `0x1f5e5f` | 792 | bin |  |  |
| 34 | `0x1f6177` | 7035 | jpg | 320x240 |  |
| 35 | `0x1f7cf2` | 294 | bin |  |  |
| 36 | `0x1f7e18` | 30454 | bmp | 216x136 |  |
| 37 | `0x1ff50e` | 4662 | bmp | 48x32 |  |
| 38 | `0x200744` | 4662 | bmp | 48x32 |  |
| 39 | `0x20197a` | 22236 | jpg | 320x240 | **main menu background** (unselected icons baked in) |
| 40 | `0x207056` | 27056 | bmp | 100x90 | **selected icon: camera** |
| 41 | `0x20da06` | 27056 | bmp | 100x90 | **selected icon: video** |
| 42 | `0x2143b6` | 27056 | bmp | 100x90 | **selected icon: gallery** |
| 43 | `0x21ad66` | 27056 | bmp | 100x90 | **selected icon: settings** |
| 44 | `0x221716` | 27056 | bmp | 100x90 | **selected icon: power** |
| 45 | `0x2280c6` | 1932 | wav | 16000 Hz, mono, 0.059 s | button click |
| 46 | `0x228852` | 2638 | wav | 16000 Hz, mono, 0.081 s | button click |
| 47 | `0x2292a0` | 2064 | wav | 16000 Hz, mono, 0.063 s | button click |
| 48 | `0x229ab0` | 58352 | wav | 16000 Hz, mono, 1.822 s | **power-off sound** |
| 49 | `0x237ea0` | 51824 | wav | 16000 Hz, mono, 1.618 s | **power-on sound** |
| 50 | `0x244910` | 13296 | wav | 16000 Hz, mono, 0.414 s | **shutter sound** |
| 51 | `0x247d00` | 3512 | bmp | 24x48 |  |
| 52 | `0x248ab8` | 3512 | bmp | 24x48 |  |
| 53 | `0x249870` | 3512 | bmp | 24x48 |  |
| 54 | `0x24a628` | 3512 | bmp | 24x48 |  |
| 55 | `0x24b3e0` | 3512 | bmp | 24x48 |  |
| 56 | `0x24c198` | 3512 | bmp | 24x48 |  |
| 57 | `0x24cf50` | 3512 | bmp | 24x48 |  |
| 58 | `0x24dd08` | 3512 | bmp | 24x48 |  |
| 59 | `0x24eac0` | 3512 | bmp | 24x48 |  |
| 60 | `0x24f878` | 3512 | bmp | 24x48 |  |
| 61 | `0x250630` | 3512 | bmp | 24x48 |  |
| 62 | `0x2513e8` | 3512 | bmp | 24x48 |  |
| 63 | `0x2521a0` | 3512 | bmp | 24x48 |  |
| 64 | `0x252f58` | 267228 | bin |  | **sprite atlas** (UI pieces; sprite #1 = the selected bar in settings) |
| 65 | `0x294334` | 1024 | bin |  | **palette for res64**: RGB565 + 5-bit alpha |
| 66 | `0x294734` | 5901 | jpg | 320x240 |  |
| 67 | `0x295e41` | 40588 | jpg | 320x240 | **switch-off screen** |
| 68 | `0x29fccd` | 40848 | jpg | 320x240 | **switch-on screen** |
| 69 | `0x2a9c5d` | 84264 | bin |  |  |
| 70 | `0x2be585` | 77968 | bin |  |  |
| 71 | `0x2d1615` | 33204 | jpg | 320x240 | **settings background** (text and icons are drawn by the firmware) |
| 72 | `0x2d97c9` | 37688 | bmp | 112x112 |  |
| 73 | `0x2e2b01` | 37688 | bmp | 112x112 |  |
| 74 | `0x2ebe39` | 37688 | bmp | 112x112 |  |
| 75 | `0x2f5171` | 696 | bmp | 10x20 |  |
| 76 | `0x2f5429` | 696 | bmp | 10x20 |  |
| 77 | `0x2f56e1` | 9 | bin |  |  |
| 78 | `0x2f56ea` | 27312 | jpg | 320x240 | **USB screen** (plugged into a PC) |
| 79 | `0x2fc19a` | 8120 | jpg | 320x240 |  |
