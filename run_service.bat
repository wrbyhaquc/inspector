@echo off
chcp 65001 > nul
rem Inspector as a background service: the UI server and the script runner, restarted if they ever stop.
rem Only one runs at a time: if Inspector is already running, this one says so and ends (it does not restart it).
rem   restart: restart_inspector.bat        stop: close this window (or end the task "Inspector")
title Inspector service
cd /d %~dp0
set PYTHONIOENCODING=utf-8
rem the logs go to the data folder (python -m project logs), never the program folder
set LOGS=
for /f "usebackq delims=" %%d in (`python -m project logs`) do set "LOGS=%%d"
if "%LOGS%"=="" set "LOGS=%~dp0logs"
if not exist "%LOGS%" mkdir "%LOGS%"
:loop
rem checked without writing to the log: a running Inspector keeps the log open
python -m server --check
if %errorlevel%==3 goto already
echo %date% %time% starting the server >> "%LOGS%\service.log"
python -m server --no-browser --start-runner >> "%LOGS%\server.log" 2>&1
if %errorlevel%==3 goto already
if %errorlevel%==4 goto toonew
echo %date% %time% the server stopped (exit %errorlevel%), restarting in 10 seconds >> "%LOGS%\service.log"
timeout /t 10 /nobreak > nul
goto loop

:already
echo Inspector is already running, so this window does not start another one. To restart it, run restart_inspector.bat.
timeout /t 8 > nul
goto :eof

:toonew
echo This Inspector is older than the one that last wrote the runtime folder (see "%LOGS%\server.log"): update Inspector.
timeout /t 30 > nul
