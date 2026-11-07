@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "UPD=%~dp0update.bat"
set "UPP=%~dp0update_prices.bat"
set "UPT=%~dp0update_today.bat"
set "VBS=%~dp0run_hidden.vbs"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$s = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2);" ^
 "$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c \"' + $env:UPD + '\"');" ^
 "$t = New-ScheduledTaskTrigger -Daily -At 05:00;" ^
 "Register-ScheduledTask -TaskName 'MP Control - daily update' -Action $a -Trigger $t -Settings $s -Force | Out-Null;" ^
 "Write-Host 'OK: daily update at 05:00 is scheduled (task: MP Control - daily update)';" ^
 "$a2 = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('\"' + $env:VBS + '\" \"' + $env:UPP + '\"');" ^
 "$t2 = @((New-ScheduledTaskTrigger -Daily -At 10:00), (New-ScheduledTaskTrigger -Daily -At 14:00), (New-ScheduledTaskTrigger -Daily -At 18:00));" ^
 "$s2 = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30);" ^
 "Register-ScheduledTask -TaskName 'MP Control - price check' -Action $a2 -Trigger $t2 -Settings $s2 -Force | Out-Null;" ^
 "Write-Host 'OK: price check at 10:00, 14:00, 18:00 is scheduled (task: MP Control - price check)';" ^
 "$a3 = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('\"' + $env:VBS + '\" \"' + $env:UPT + '\"');" ^
 "$t3 = New-ScheduledTaskTrigger -Daily -At 07:00;" ^
 "$t3.Repetition = (New-ScheduledTaskTrigger -Once -At 07:00 -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Hours 17)).Repetition;" ^
 "$s3 = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20);" ^
 "Register-ScheduledTask -TaskName 'MP Control - today orders' -Action $a3 -Trigger $t3 -Settings $s3 -Force | Out-Null;" ^
 "Write-Host 'OK: today orders every 30 min 07:00-24:00 is scheduled (task: MP Control - today orders)'"
pause
