@echo off
chcp 65001 >nul
schtasks /Create /F /TN "AgentToolRadar-DailyFetch" /SC DAILY /ST 09:10 /TR "\"%~dp0update.bat\""
echo.
echo 已创建 Windows 计划任务：每天 09:10 自动运行 update.bat 抓取最新数据（无需打开软件）。
echo 查看任务：schtasks /Query /TN "AgentToolRadar-DailyFetch"
echo 删除任务：schtasks /Delete /TN "AgentToolRadar-DailyFetch" /F
pause
