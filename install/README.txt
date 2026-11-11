RECEIPT QUEST - camera installer (Windows, Python 3, nothing else)

  1_FIND_CAMERA.bat     camera plugged in and switched on; looks only
  2_PREPARE_USB.bat     lets Windows set up the chip loader's driver; writes nothing
  3_BACKUP.bat          full firmware backup (5-10 min) + "is this the tested camera?"
                        KEEP the firmware_backup_... folder it makes. Copy it somewhere safe.
  LIST_MODS.bat         the mods here, and whether your backup fits them

  INSTALL_PRINT_EFFECT.bat     / UNDO_PRINT_EFFECT.bat
  INSTALL_SOUNDS.bat           / UNDO_SOUNDS.bat
  INSTALL_FRAMES.bat           / UNDO_FRAMES.bat
  INSTALL_SCREENS_1_MENUS.bat  / UNDO_SCREENS_1_MENUS.bat
  INSTALL_SCREENS_2_STARTUP.bat/ UNDO_SCREENS_2_STARTUP.bat   (after SCREENS_1)

Click Yes when Windows asks to allow changes. If Windows offers to FORMAT a disk: Cancel.
Leave the camera plugged in and alone until a window says Done.
If a run stops half-way: leave the camera plugged in and run the same file again.

Full guide: ../docs/INSTALL.md     Problems: ../docs/TROUBLESHOOTING.md
