@echo off
setlocal
cd /d "%~dp0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /C:"LISTENING" ^| findstr /C:":17920 "') do (
  taskkill /PID %%P /F >nul 2>&1
)
exit /b 0
