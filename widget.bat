@echo off
chcp 65001 >nul
rem Запуск виджета Mocheqi поверх всех окон (без чёрного окна).
cd /d "%~dp0app"
where pyw >nul 2>&1 && (start "" pyw -3 widget.pyw & exit /b)
where pythonw >nul 2>&1 && (start "" pythonw widget.pyw & exit /b)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" (start "" "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" widget.pyw & exit /b)
echo Не нашёл Python. Запустите start.bat — он подскажет, что установить.
pause
