@echo off
chcp 65001 >nul
rem Добавляет виджет в автозагрузку Windows (запускается при входе в систему).
set "TARGET=%~dp0widget.bat"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$p = [Environment]::GetFolderPath('Startup') + '\Mocheqi widget.lnk';" ^
 "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($p); $s.TargetPath = $env:TARGET; $s.WorkingDirectory = (Split-Path $env:TARGET); $s.WindowStyle = 7; $s.Save();" ^
 "Write-Host 'OK: виджет будет запускаться при входе в Windows. Убрать: удалить ярлык Mocheqi widget в папке автозагрузки (Win+R, shell:startup).'"
call "%TARGET%"
pause
