@echo off
title Receipt Quest - firmware backup (read only)
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
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Asking Windows for permission - click Yes on the prompt.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
echo.
echo  Step 3: copies the camera's whole firmware to this folder, twice, and compares.
echo  About 5-10 minutes. Nothing is written to the camera.
echo  Then it checks whether this camera matches the tested one.
echo  Leave the camera plugged in and alone until this says Done.
echo  If Windows asks to FORMAT a disk, click CANCEL. Never format it.
echo.
%PY% rq_usb_step4.py
echo.
echo Done. This window closes in 300 seconds - or close it now.
timeout /t 300 >nul
