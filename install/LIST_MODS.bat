@echo off
title Receipt Quest - list the mods
cd /d "%~dp0"
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo Python 3 is not installed. Get it from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH" in the installer^), then run this again.
  pause
  exit /b
)
echo.
echo  The mods in this folder and whether your backup fits them.
echo  No USB, nothing is sent to the camera.
echo.
%PY% rq_install.py list
echo.
echo Done. This window closes in 300 seconds - or close it now.
timeout /t 300 >nul
