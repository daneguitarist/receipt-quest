# Troubleshooting

Every step writes a `log_....txt` in the `install` folder, and every install/undo makes a
`write_...` folder with `journal.jsonl` (one line per erase/program) and `report.json`.
When asking for help, attach the log - it contains no firmware.

## "If a run stops in the middle"

**Leave the camera plugged in and switched on**, and run the same `.bat` again. It reads
the flash, sees which sectors are already done, which are half-written, and continues.
When a sector fails to verify three times, the installer leaves the camera in loader
mode on purpose, so USB stays usable for the next try.

## Messages and what to do

**"Python 3 is not installed"** - install it from python.org and tick "Add python.exe to
PATH", then run the file again.

**The "allow this app to make changes" prompt didn't come / timed out** - it gives up after
about 2 minutes. Run the file again.

**"camera not found in normal USB mode"** - switch the camera on, use a data cable (not a
charge-only one), try another USB port. In Explorer it should appear as a drive.

**"DestBin.bin is on the card - stopped"** - move that file off the card first. It is the
camera maker's update file; at the next start-up the camera would rewrite its whole flash
with it.

**"loader disk did not appear within 20 s"** - run `2_PREPARE_USB.bat` again (Windows may
still be setting up the loader's driver), then the step you were on.

**Windows offers to format a disk** - click **Cancel**. That's the loader showing up as an
unformatted disk. Never format it.

**"loader ID differs" / "chip ROM check failed"** - this isn't the chip the tools know.
Nothing was written. Open an issue with the log.

**Backup says "NO - do not install anything"** - your firmware differs from the tested one
(or the camera was already modified some other way). Nothing was written. The lines above
it list which 4 KiB sectors differ; open an issue with them. Keep the backup anyway.

**"two reads DIFFER"** - USB trouble while reading. Try another port or cable and run the
backup again. No `BACKUP_firmware.bin` is made unless both reads agree.

**"sector ... is neither stock, ours, nor a half-written copy - stopped before writing"** -
something else has changed those sectors (another tool, or a different version of the
same mod). Nothing was written. The installer will not overwrite what it doesn't
recognise, and neither will the undo. Open an issue.

**"this pack needs 'screens-menus' on the camera first"** - install `SCREENS_1_MENUS`
before `SCREENS_2_STARTUP`.

**"STOPPED with this sector not verified"** - don't unplug, don't switch off. Run the same
file again. If it keeps failing on the same sector, open an issue with the `write_...`
folder's `journal.jsonl`.

**"the final full read-back failed"** - every sector was already verified one by one; run
the same file again and it should say "already written".

## The camera behaves oddly after an install

- **Prints look normal (no pixel art) after `PRINT_EFFECT`**: the effect stepped aside on
  purpose for that print (it does that for anything unexpected rather than risk a bad
  print). Tell us what you printed, from which screen, and the camera's settings.
- Anything else: run the matching `UNDO_....bat`. Undo needs the camera to reach USB mode
  (switch on, plug in). None of the program sectors the mods write hold code the camera
  runs at power-on, so a camera that shows its USB screen can always be put back.

## The camera doesn't start at all

This hasn't happened, but here's the way back: the flash chip (8 pins, GD25Q32 or
similar, 4 MiB) can be written directly with a cheap SPI programmer (CH341A-type) and a
SOIC-8 clip, using your `BACKUP_firmware.bin`. That means opening the camera; the
[penguin-camera](https://github.com/hidoba/penguin-camera) project documents recovery on
its sister model. This is why step 3 says to keep the backup folder somewhere safe.
