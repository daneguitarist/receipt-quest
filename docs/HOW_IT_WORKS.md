# How it works

The short version: the camera's chip has a loader burned into it. One USB command wakes it,
and the loader has a "copy memory, then call this address" routine. We use that routine
to run two tiny programs in the chip's scratch RAM: one reads the SPI flash, one erases
and programs it. Everything else is careful bookkeeping around those two programs.

All numbers below are for the AX3291A with firmware 20240822_V1.9.

## 1. The camera over USB, normal mode

Switched on and plugged in, the camera is a USB mass-storage device `0219:3280`. SCSI
INQUIRY says vendor `Buildwin`, product `Media-Player`, revision `1.00`; the disk is the
SD card. `install/rq_usb_probe.py` only sends TEST UNIT READY, INQUIRY and READ CAPACITY.

On Windows the tools talk to the disk with `IOCTL_SCSI_PASS_THROUGH_DIRECT` on
`\\.\PhysicalDriveN`, which needs administrator rights (hence the "allow changes" prompt).
Before any vendor command the card's volumes are flushed and dismounted, exactly like a
safe eject.

## 2. The ROM door: `0xDA`

A 16-byte CDB starting `DA`, no data. The firmware hands control to the chip's boot ROM,
which re-enumerates as a different USB disk: **`1908:3319`**, the boot-ROM loader. Its
INQUIRY and REQUEST SENSE answers are byte-identical to the ones from the AX3295B
"penguin" camera, and so is the 32 KiB ROM itself (sha256 `62d4dabe...`), so everything
[penguin-camera](https://github.com/hidoba/penguin-camera) learned about that loader
applies here.

The loader has an idle watchdog: if nobody talks to it for about a second and a half, the
camera restarts into its normal firmware. The very first time, Windows is still
installing a driver for the new device when that happens - `2_PREPARE_USB.bat` simply
tries up to three times and keeps the loader awake with harmless questions once it's
reachable. After that, the driver is there and the loader is ready within a fraction of a
second.

"Safely removing" the loader disk lets the watchdog restart the camera normally.

## 3. The loader's memory routine: `0xCB`

```
CB | routine (u32 LE) | address (u32 LE) | callback (u32 LE) | b13 b14 b15
```

With `routine = 0x00102620` (the ROM's memory-transfer routine), data direction IN, the ROM
calls `callback(r3 = address, r4 = length, r5 = CDB bytes 13..15 + one more byte)` and
then sends `length` bytes from `address` to the PC. Data direction OUT: it receives
`length` bytes into `address` and then calls the callback. `callback = 0xFFFFFFFF` means
none, which gives plain memory reads and writes. `install/rq_usb_step3.py` proves the
routine address by reading the ROM's INQUIRY text back, then reads the whole ROM twice.

Every 0xCB the tools send goes through a fence in the PC code first (`check()` in
`rq_install.py`): which routine, which addresses, which callbacks, which lengths, and -
for erase and program - which flash sectors are in the current plan.

## 4. Two tiny helper programs in scratch RAM

The loader's scratch SRAM from `0x4800` to `0x4c00` is free while the loader runs and is
wiped when the camera restarts. The helpers are assembled in Python (`rq_stub.py`,
`rq_stub_w.py`) for the chip's CPU: OpenRISC 1000, **little-endian, no branch delay
slots**. They only use the ROM's own SPI building blocks:

| ROM address | does |
|---|---|
| `0x104898` | chip select low |
| `0x1048c8` | chip select high |
| `0x104808` | SPI send mode |
| `0x104838` | SPI receive mode |
| `0x10485c` | exchange one byte (r3 out, r11 in) |

and kick the ROM's own watchdog (`mtspr 0x880c, 0x5001d`) while waiting.

**Reader** (448 bytes, `rq_stub.py`): `JEDEC` sends `9F` and returns the 3-byte flash ID;
`READ` sends `03 + address` and returns up to 256 bytes. These are the only two flash
commands it can put on the wire. A full 4 MiB read takes about 25 seconds.

**Writer** (at most 888 bytes of code, `rq_stub_w.py`), buffer at `0x4b80` (128 bytes):

| entry | direction | does |
|---|---|---|
| `STAT` | in, 2 bytes | status registers 1 (`05`) and 2 (`35`) |
| `READ` | in, 1..128 bytes | `03` read, for verifying |
| `ERASE` | in, 1 byte | `06`, `20 addr` (4 KiB sector erase), poll `05`; returns the final status (`EE` = refused) |
| `PROG` | out, 128 bytes | `06`, `02 addr` + 128 bytes, poll `05`; status byte at `0x4b78` |

The writer is **built for one mod at a time**: the allowed sector windows are compiled
into its code, and it checks every erase/program address against them (and alignment,
buffer and length) before a single SPI byte goes out. It has no chip erase, no block
erase and no status-register write. The windows can never include sectors `0x0`-`0x2`
(boot), `0x61` (code the camera runs at power-on), `0xb1` (resource table) or `0x2ff`
(settings) - the Python refuses to build such a helper.

## 5. One install, start to finish

`rq_install.py install NAME`:

1. **Check the backup.** Your newest `firmware_backup_*/BACKUP_firmware.bin` must match
   the reference (`install/reference/*.json`: sha256 of every 4 KiB sector of a stock
   camera; only the settings sector `0x2ff000` may differ).
2. **Rebuild the mod from your backup.** `packs/NAME.rqp` + `NAME.json` (see below). Every
   rebuilt sector's sha256 must equal the tested one; every other sector must be untouched.
3. **Loader:** `0xDA`, check its INQUIRY, read the chip ROM and check its sha256.
4. **Upload the reader**, read it back to check it landed, check the flash ID is
   `c8 40 16` (GD25Q32), read the whole flash ("before.bin").
5. **Plan:** for each sector the mod changes - already right? skip. Stock, ours, or a
   half-written copy of ours (every byte either `FF` or the target)? Write it. Anything
   else? Stop before writing anything.
6. **Upload the writer** (built for this mod's windows), read it back, check the flash
   isn't write-protected or busy.
7. **Write**, one sector at a time: erase, read back blank, program 32 x 128 bytes, read
   back and compare, up to 3 attempts; a line in `journal.jsonl` for every step. The
   switch-on screen and sound are written last; the print hooks are switched over last
   and switched back first (`last_install` / `last_undo` in the pack).
8. **Upload the reader again**, read the whole flash ("after.bin"), and check it equals
   "before" with exactly the planned sectors changed.
9. Let the loader go; the camera restarts normally.

Each run gets its own `write_<action>_<name>_<time>` folder with `before.bin`,
`after.bin`, `journal.jsonl` and `report.json`.

The program sectors the print effect changes (`0xe000`, `0xf000`, `0x18000`) hold no code
that runs at power-on. That was checked against the firmware's call graph: the camera
reaches its USB mode without ever running them, so even a damaged effect install can be
fixed over USB.

## 6. Patch packs: sharing mods without sharing firmware

The camera's firmware belongs to its maker, so it isn't in this project - not even the
sectors a mod changes. A pack holds only:

- **literal records:** new bytes (your sound, your picture, your code), and
- **copy records:** "copy N bytes from stock flash offset X". Any run of 32+ bytes that
  already exists somewhere in the stock flash (JPEG headers, for example) is stored this
  way and rebuilt from your own backup.

Format (`.rqp`, little-endian):

```
"RQP1" | u32 count | count x ( u32 dst | u32 length | u32 src | [length bytes if src == 0xFFFFFFFF] )
```

The `.json` next to it lists the sector windows, the sha256 of every changed sector before
and after, write-order hints (`last_install`, `last_undo`), dependencies (`requires`) and
the sha256 of the `.rqp`. `make/make_pack.py` makes one from a stock backup and a modded
image, and checks that it rebuilds the image exactly. See [MAKING_MODS.md](MAKING_MODS.md).

## 7. Testing without a camera

`install/tests/test_install_offline.py STOCK_BACKUP.bin WORKDIR` runs the real installer
against a simulated camera: a fake loader that behaves like the ROM's 0xCB routine, the
real writer helper running in an OpenRISC interpreter, a NOR-flash model that flags any
illegal command, and ~3% of USB replies dropped (half of them after the command already
happened). It installs and undoes every pack, interrupts writes half-way, plants
unexpected bytes, damages a pack and offers a backup from a different firmware - and
checks the whole simulated flash after every step. `test_rq_stub.py` and
`test_rq_stub_w.py` test the two helpers on their own.
