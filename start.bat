@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=
py -3 -c "import sys" >nul 2>&1 && set PY=py -3
if not defined PY python -c "import sys" >nul 2>&1 && set PY=python
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
  echo Python not found. Run probe_api.bat first - it installs Python.
  pause
  exit /b 1
)
%PY% -c "import openpyxl" >nul 2>&1 || %PY% -m pip install --quiet openpyxl
cd app
%PY% server.py
pause
