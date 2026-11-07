@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=
py -3 -c "import sys" >nul 2>&1 && set PY=py -3
if not defined PY python -c "import sys" >nul 2>&1 && set PY=python
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
  echo Python not found. Run probe_api.bat first.
  pause
  exit /b 1
)
echo Full history load: WB and Ozon since 01.01.2026. This takes 10-20 minutes. VPN must be OFF.
cd app
%PY% collector.py --full
echo.
echo Done. Now start start.bat
pause
