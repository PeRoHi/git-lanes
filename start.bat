@echo off
setlocal
cd /d "%~dp0"

call "%~dp0scripts\find-python.cmd"
set "PYW_EXE="
if exist "%TEMP%\git-lanes-pyw.txt" (
  for /f "usebackq delims=" %%I in ("%TEMP%\git-lanes-pyw.txt") do set "PYW_EXE=%%I"
)
if defined PYW_EXE (
  start "" "%PYW_EXE%" "%~dp0scripts\launch.py"
  exit /b 0
)

powershell -NoProfile -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Python 3.10 or newer was not found. Install Python and retry. See README.md','Git Lanes')"
exit /b 1
