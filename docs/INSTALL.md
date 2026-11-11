# Installing, step by step (Windows)

No coding needed. Every step is a file you double-click in the `install` folder.

## Before you start

- A Windows PC (10 or 11).
- **Python 3** from <https://www.python.org/downloads/>. In the installer, tick
  **"Add python.exe to PATH"**. Nothing else to install - the camera tools only use what
  comes with Python.
- The camera, a **charged battery**, and its USB cable (a data cable, not charge-only).
- An SD card in the camera, as usual.
- **Never put a file called `DestBin.bin` on the camera's card.** That's the maker's own
  update file; the camera would rewrite its whole flash with it on the next start. The
  tools refuse to run if they see one.

Download the project (green **Code** button on GitHub, then **Download ZIP**) and unzip it
somewhere easy, like your Desktop.

## Every time you run a step

- Windows asks **"Do you want to allow this app to make changes to your device?"** Click
  **Yes**. Talking to a USB device this directly needs administrator rights. The prompt
  gives up after about 2 minutes; if you miss it, just run the file again.
- During a run the camera restarts into a hidden loader and back. Windows may play the
  "device connected" sounds a few times. That's expected.
- If Windows ever asks to **format** a disk: click **Cancel**. Always.
- Leave the camera plugged in and alone until the window says **Done**.
- Each step writes a `log_....txt` next to it. If something goes wrong, that file is what
  to paste into an issue.

## Step 1 - `1_FIND_CAMERA.bat` (looks only)

Plug the camera in and switch it on. It shows up as a USB drive (its SD card). This step
asks it the three standard questions every USB drive answers and checks it calls itself
**Buildwin Media-Player**. Nothing is changed.

## Step 2 - `2_PREPARE_USB.bat` (writes nothing)

Sends the camera one command that makes its chip restart into the loader built into the
chip itself, up to three times. The first time, Windows needs a moment to set up a driver
for that loader, and the loader gives up waiting after a second or two - so this step
just gives Windows a few chances. At the end it should say it talked to the loader and
that its answers are the same as the penguin camera's chip ROM.

## Step 3 - `3_BACKUP.bat` (reads only, 5-10 minutes)

Copies the camera's whole 4 MiB firmware to a new `firmware_backup_<date>` folder, twice,
and compares the two copies. Then:

```
IS THIS CAMERA THE TESTED ONE?
  every sector matches the tested firmware (the settings sector is allowed to differ)
  YES - the mods in this folder fit this camera. Keep this backup folder safe.
```

**Keep that folder.** Copy it somewhere else too (a USB stick, cloud storage). It is the
only exact copy of your camera's original firmware, and every `UNDO_...` uses it.

If it says **NO**: stop here. Your camera has a different firmware (or it was already
modified). Nothing was written. Open an issue and paste the lines it printed - they list
sector numbers, no firmware.

`LIST_MODS.bat` (no admin, no USB) shows every mod in the folder and whether your backup
fits it.

## Step 4 - install what you like

| File | Takes | Then try |
|---|---|---|
| `INSTALL_PRINT_EFFECT.bat` | ~1 min | take a photo and print it |
| `INSTALL_SOUNDS.bat` | ~1.5 min | press buttons, switch off and on |
| `INSTALL_FRAMES.bat` | ~3 min | frames in the photo screen |
| `INSTALL_SCREENS_1_MENUS.bat` | ~1.5 min | the main menu and settings |
| `INSTALL_SCREENS_2_STARTUP.bat` | ~1 min | switch off and on, plug into the PC |

`SCREENS_2` only runs after `SCREENS_1` is on the camera (that proves your camera shows the
new pictures properly before its start-up screen is changed).

A good run ends with:

```
VERDICT:
  whole flash = before + exactly the planned sectors: True
  PRINT EFFECT WRITTEN
...
camera is back in normal USB mode with its card
```

Then unplug the camera and try it.

## Undo

Every mod has an `UNDO_....bat`. It puts exactly that mod's sectors back the way they are
in your backup and leaves the other mods alone. Undo the start-up screens before the menus
if you want to remove both.

## The camera's own settings that still matter

- **Print Density** (settings page 1) is the darkness knob, and it works with the print
  effect: the effect makes the picture, then the camera burns it with your density
  setting. Darker = deeper blacks and heavier greys; too dark and the two greys merge.
- **Time stamp** (settings page 2) turns the date on prints on or off. If it's on, the date
  gets pixel-arted along with the photo.
- **Image Quality** hardly matters any more: the effect averages the photo into fat
  pixels anyway.
