@echo off
title Receipt Quest - install new camera sounds
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
echo  Install: new camera sounds
echo  About 2 minutes.
echo  Leave the camera plugged in and alone until this says Done.
echo  The camera restarts into its loader and back - that is expected.
echo  If Windows asks to FORMAT a disk, click CANCEL. Never format it.
echo.
%PY% rq_install.py install sounds
echo.
echo Done. This window closes in 120 seconds - or close it now.
timeout /t 120 >nul
