@echo off
chcp 65001 >nul
rem Удаляет задачи Windows дашборда — после переезда на сервер загрузки делает сервер.
schtasks /Delete /TN "MP Dashboard - daily update" /F
schtasks /Delete /TN "MP Dashboard - price check" /F
schtasks /Delete /TN "MP Dashboard - today orders" /F
echo Готово: задачи на этом компьютере удалены.
pause
