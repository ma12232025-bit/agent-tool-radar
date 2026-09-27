@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动 Agent 工具雷达 ...
set PY=python
where py >nul 2>nul && set PY=py
%PY% app.py
pause
