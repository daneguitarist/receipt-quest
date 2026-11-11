@echo off
title Receipt Quest - find the camera (look only)
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
echo  Step 1: is the camera there, and is it the right one?
echo  Only standard read-only questions are sent. Nothing is changed.
echo.
%PY% rq_usb_probe.py
echo.
echo Done. This window closes in 60 seconds - or close it now.
timeout /t 60 >nul
