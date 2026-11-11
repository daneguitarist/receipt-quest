@echo off
title Receipt Quest - prepare USB (nothing written)
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
echo  Step 2: restarts the camera into its chip's built-in loader, up to 3 times,
echo  so Windows can set up its driver. Only standard questions are asked.
echo  Nothing is written anywhere.
echo  If Windows asks to FORMAT a disk, click CANCEL. Never format it.
echo.
%PY% rq_usb_step2b.py
echo.
echo Done. This window closes in 60 seconds - or close it now.
timeout /t 60 >nul
