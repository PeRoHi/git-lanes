@echo off
setlocal
cd /d "%~dp0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":17920 .*LISTENING"') do (
  taskkill /PID %%P /F >nul 2>&1
)
exit /b 0
