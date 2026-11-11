RECEIPT QUEST - one-click camera converter

ONE TIME:   double-click SETUP.bat (installs what it needs into the .venv
            folder here - your main Python is not touched).

EVERY TIME: 1. take photos with the camera as normal
            2. plug the camera into this PC
            3. double-click MAKE_PRINTS.bat
            4. it ejects the camera when done - unplug it and print the
               photos from Playback. They're now Receipt Quest prints.

What it does: every photo the camera took gets backed up to the originals
folder here, turned into pixel art (+ subtle glitches, sometimes the game
status bars, no date stamp) and put back on the card under the same name.
Prints are tagged so they never get converted twice.

settings.txt  - grey vs dots, glitches on/off, bars on/off/random
prints_log.csv - every print with its seed, so a favourite can be remade
last_run_log.txt - what happened last time
