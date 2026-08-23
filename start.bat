@echo off
setlocal
cd /d "%~dp0"
start "" pythonw "%~dp0scripts\launch.py"
exit /b 0
