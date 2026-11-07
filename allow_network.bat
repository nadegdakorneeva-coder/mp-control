@echo off
chcp 65001 >nul
rem Открывает порт 8765 дашборда для других компьютеров и телефонов в этой (домашней/офисной) сети.
rem Запускать правой кнопкой -> "Запуск от имени администратора".
netsh advfirewall firewall delete rule name="MP Dashboard 8765" >nul 2>&1
netsh advfirewall firewall add rule name="MP Dashboard 8765" dir=in action=allow protocol=TCP localport=8765 profile=private,domain
if errorlevel 1 (
  echo Не получилось. Запустите этот файл от имени администратора.
) else (
  echo Готово: порт 8765 открыт для локальной сети.
  echo Теперь в config.ini добавьте раздел:
  echo [server]
  echo network = 1
  echo и перезапустите start.bat.
)
pause
