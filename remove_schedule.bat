@echo off
chcp 65001 >nul
rem Удаляет задачи Windows MP Control (задачи дашборда Mocheqi не трогает) — после переезда на сервер загрузки делает сервер.
schtasks /Delete /TN "MP Control - daily update" /F
schtasks /Delete /TN "MP Control - price check" /F
schtasks /Delete /TN "MP Control - today orders" /F
echo Готово: задачи на этом компьютере удалены.
pause
