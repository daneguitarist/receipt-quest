@echo off
title Receipt Quest
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run SETUP.bat first.
  timeout /t 15 >nul
  exit /b 1
)
.venv\Scripts\python.exe rq_camera.py
echo.
echo Done. This window closes in 30 seconds.
timeout /t 30 >nul
