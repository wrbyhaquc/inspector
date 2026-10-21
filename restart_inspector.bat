@echo off
chcp 65001 > nul
rem Restart Inspector: stop the script runner properly, end the running service, start run_service.bat again.
rem Double-click it (or run it from a normal command window).
cd /d %~dp0
echo Stopping the script runner...
curl -s -X POST http://127.0.0.1:8765/api/shadow/stop > nul 2>&1
timeout /t 5 /nobreak > nul
echo Closing the running Inspector...
rem the service loop first (so it does not start the server again), then the server and the runner
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'run_service\.bat' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'python.*-m (server|runtime)' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 3 /nobreak > nul
rem touch watchers (adb getevent) of the ended runner would otherwise stay behind
powershell -NoProfile -Command "$all = Get-CimInstance Win32_Process; $ids = $all.ProcessId; $all | Where-Object { $_.CommandLine -match 'getevent' -and ($ids -notcontains $_.ParentProcessId) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo Starting Inspector...
start "Inspector service" /min "%~dp0run_service.bat"
echo Done: Inspector is back in a few seconds (the script runner starts too; stopped / paused devices stay as they were).
timeout /t 5 > nul
