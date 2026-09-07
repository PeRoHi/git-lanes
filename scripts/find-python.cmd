@echo off
rem Writes PY_EXE and PYW_EXE into %%TEMP%%\git-lanes-pyexe.txt and git-lanes-pyw.txt
rem ASCII only.

setlocal EnableDelayedExpansion

set "SCRIPTS=%~dp0"
set "ROOT=%SCRIPTS%.."
set "OUT_PY=%TEMP%\git-lanes-pyexe.txt"
set "OUT_PYW=%TEMP%\git-lanes-pyw.txt"
set "PY_TMP=%TEMP%\git-lanes-pyexe-raw.txt"
set "PY_EXE="
set "PYW_EXE="

if exist "!ROOT!\.venv\Scripts\pythonw.exe" (
  set "PYW_EXE=!ROOT!\.venv\Scripts\pythonw.exe"
  if exist "!ROOT!\.venv\Scripts\python.exe" (
    set "PY_EXE=!ROOT!\.venv\Scripts\python.exe"
  ) else (
    set "PY_EXE=!PYW_EXE!"
  )
  goto :write
)

del "!PY_TMP!" >nul 2>&1
py -3 -c "import sys; print(sys.executable)" > "!PY_TMP!" 2>nul
if not exist "!PY_TMP!" (
  if exist "%LocalAppData%\Programs\Python\Launcher\py.exe" (
    "%LocalAppData%\Programs\Python\Launcher\py.exe" -3 -c "import sys; print(sys.executable)" > "!PY_TMP!" 2>nul
  )
)
if exist "!PY_TMP!" (
  for /f "usebackq delims=" %%I in ("!PY_TMP!") do set "PY_EXE=%%I"
  del "!PY_TMP!" >nul 2>&1
)
if defined PY_EXE (
  for %%I in ("!PY_EXE!") do set "PY_DIR=%%~dpI"
  if exist "!PY_DIR!pythonw.exe" (
    set "PYW_EXE=!PY_DIR!pythonw.exe"
  ) else (
    set "PYW_EXE=!PY_EXE!"
  )
  goto :write
)

for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
  if exist "%%D\pythonw.exe" (
    set "PYW_EXE=%%D\pythonw.exe"
    if exist "%%D\python.exe" set "PY_EXE=%%D\python.exe"
    if not defined PY_EXE set "PY_EXE=!PYW_EXE!"
    goto :write
  )
)

for /d %%D in ("%UserProfile%\.pyenv\pyenv-win\versions\*") do (
  if exist "%%D\pythonw.exe" (
    set "PYW_EXE=%%D\pythonw.exe"
    if exist "%%D\python.exe" set "PY_EXE=%%D\python.exe"
    if not defined PY_EXE set "PY_EXE=!PYW_EXE!"
    goto :write
  )
)

for /f "delims=" %%I in ('where pythonw 2^>nul') do (
  set "CAND=%%I"
  if /I "!CAND:WindowsApps=!"=="!CAND!" (
    set "PYW_EXE=!CAND!"
    for %%J in ("!CAND!") do set "PY_DIR=%%~dpJ"
    if exist "!PY_DIR!python.exe" set "PY_EXE=!PY_DIR!python.exe"
    if not defined PY_EXE set "PY_EXE=!PYW_EXE!"
    goto :write
  )
)

for /f "delims=" %%I in ('where python 2^>nul') do (
  set "CAND=%%I"
  if /I "!CAND:WindowsApps=!"=="!CAND!" (
    set "PY_EXE=!CAND!"
    for %%J in ("!CAND!") do set "PY_DIR=%%~dpJ"
    if exist "!PY_DIR!pythonw.exe" (
      set "PYW_EXE=!PY_DIR!pythonw.exe"
    ) else (
      set "PYW_EXE=!PY_EXE!"
    )
    goto :write
  )
)

:write
if not defined PY_EXE if defined PYW_EXE set "PY_EXE=!PYW_EXE!"
if not defined PYW_EXE if defined PY_EXE set "PYW_EXE=!PY_EXE!"
if defined PY_EXE (
  >"!OUT_PY!" echo !PY_EXE!
) else (
  del "!OUT_PY!" >nul 2>&1
)
if defined PYW_EXE (
  >"!OUT_PYW!" echo !PYW_EXE!
) else (
  del "!OUT_PYW!" >nul 2>&1
)
endlocal
