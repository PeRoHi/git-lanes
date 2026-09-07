@echo off
setlocal
cd /d "%~dp0"

call "%~dp0scripts\find-python.cmd"
set "PY_EXE="
if exist "%TEMP%\git-lanes-pyexe.txt" (
  for /f "usebackq delims=" %%I in ("%TEMP%\git-lanes-pyexe.txt") do set "PY_EXE=%%I"
)
if defined PY_EXE (
  "%PY_EXE%" "%~dp0scripts\launch.py"
  exit /b %errorlevel%
)

echo Python 3.10 or newer was not found. See README.md
pause
exit /b 1
