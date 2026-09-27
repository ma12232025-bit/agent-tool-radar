@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py
if not exist "%~dp0data" mkdir "%~dp0data"
%PY% fetcher.py --once >> "%~dp0data\update.log" 2>&1
