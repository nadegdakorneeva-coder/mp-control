@echo off
chcp 65001 >nul
cd /d "%~dp0.."
rem Готовит файлы для переноса на сервер: закрывает базу и копирует config.ini и mp.sqlite в server\to_upload
set PY=
py -3 -c "import sys" >nul 2>&1 && set PY=py -3
if not defined PY set PY=python
echo Закройте окно дашборда (start.bat) и виджет, затем нажмите любую клавишу.
pause >nul
%PY% -c "import sqlite3; c=sqlite3.connect(r'data\mp.sqlite'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()" || (echo Не удалось закрыть базу — дашборд ещё запущен? & pause & exit /b 1)
if not exist "server\to_upload" mkdir "server\to_upload"
copy /Y "config.ini" "server\to_upload\config.ini" >nul
copy /Y "data\mp.sqlite" "server\to_upload\mp.sqlite" >nul
echo.
echo Готово. Файлы для загрузки на сервер лежат в папке:
echo   %CD%\server\to_upload
echo Перетащите оба файла в WinSCP в домашнюю папку на сервере. После переноса удалите папку to_upload — в ней ключи.
explorer "server\to_upload"
pause
