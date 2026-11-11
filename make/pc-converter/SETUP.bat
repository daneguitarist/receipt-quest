@echo off
title Receipt Quest setup
cd /d "%~dp0"
echo Setting up Receipt Quest (one time, a couple of minutes)...
echo setup started %date% %time% > setup_log.txt
if not exist .venv (
  py -3 -m venv .venv >> setup_log.txt 2>&1
)
.venv\Scripts\python.exe -m pip install --upgrade pip >> setup_log.txt 2>&1
.venv\Scripts\python.exe -m pip install -r requirements.txt >> setup_log.txt 2>&1
.venv\Scripts\python.exe -c "import numpy, scipy, skimage, PIL, cv2; print(\"SETUP OK\", numpy.__version__, scipy.__version__, skimage.__version__, PIL.__version__, cv2.__version__)" >> setup_log.txt 2>&1
echo setup finished %date% %time% >> setup_log.txt
type setup_log.txt | findstr /C:"SETUP OK"
echo.
echo Done. This window closes in 15 seconds.
timeout /t 15 >nul
