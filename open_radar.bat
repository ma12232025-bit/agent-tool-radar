@echo off
set "APPDIR=%~dp0"
REM If service is already running, just open the website
curl -m 2 -s -o nul http://127.0.0.1:8765/api/stats >nul 2>&1
if %errorlevel%==0 goto open
set PY=python
where py >nul 2>nul && set PY=py
REM Start service minimized (visible in taskbar, close its window to stop)
start "AgentToolRadar-Service" /min /d "%APPDIR%" cmd /c "%PY% app.py"
set /a TRY=0
:waitloop
ping -n 2 127.0.0.1 >nul
curl -m 2 -s -o nul http://127.0.0.1:8765/api/stats >nul 2>&1
if not errorlevel 1 goto open
set /a TRY+=1
if %TRY% lss 20 goto waitloop
echo Service failed to start. Please check Python installation.
pause
exit /b 1
:open
start "" http://localhost:8765
exit /b 0
