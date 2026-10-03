@echo off
rem ==========================================================================
rem  sim.bat  -  launcher only: find Python, run sim.py, pause on double-click
rem
rem  All of the real logic lives in sim.py next to this file.  This wrapper
rem  exists because Windows needs a .bat to handle a double-click, and because
rem  a .bat is the only place that knows whether the console will vanish.
rem
rem  Requires: Python 3  +  Icarus Verilog (iverilog + vvp)  +  GTKWave
rem  Fallback: sim_batch_only.bat  (same features, pure batch, no Python)
rem ==========================================================================
setlocal EnableExtensions EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

if not exist "%SCRIPT_DIR%\sim.py" (
    echo [ERROR] sim.py is missing next to this launcher:
    echo         %SCRIPT_DIR%\sim.py
    set "RC=1"
    goto finish
)

rem ------------------------- find an interpreter ----------------------------
set "PY="
set "PYARGS="

rem 1) the py launcher is the most reliable choice on Windows
if not defined PY (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PY=py"
        set "PYARGS=-3"
    )
)

rem 2) python.exe on PATH, but skip the Microsoft Store stub in WindowsApps
if not defined PY (
    for /f "delims=" %%p in ('where python 2^>nul') do (
        if not defined PY (
            echo %%p | find /i "WindowsApps" >nul
            if errorlevel 1 set "PY=%%p"
        )
    )
)

rem 3) the usual per-user install location
if not defined PY (
    for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
        if not defined PY if exist "%%~fd\python.exe" set "PY=%%~fd\python.exe"
    )
)

if not defined PY (
    echo [ERROR] Python 3 was not found.
    echo         install Python 3, or use the pure batch version instead:
    echo             sim_batch_only.bat
    set "RC=1"
    goto finish
)

rem ------------------------- run sim.py --------------------------------------
"%PY%" %PYARGS% "%SCRIPT_DIR%\sim.py" %*
set "RC=%ERRORLEVEL%"

rem ------------------------- pause when double-clicked ----------------------
rem -q / --no-pause means "never pause"; "sim.bat" appearing in the command
rem line means cmd was started just for this file, i.e. an Explorer double-click.
set "ARGS=%*"
if not "!ARGS:-q=!"=="!ARGS!"         set "NOPAUSE=1"
if not "!ARGS:--no-pause=!"=="!ARGS!" set "NOPAUSE=1"
if "%NOPAUSE%"=="1" exit /b %RC%

set "CMDLINE=%cmdcmdline%"
if defined CMDLINE set "CMDLINE=%CMDLINE:"=%"
if not "!CMDLINE:%~nx0=!"=="!CMDLINE!" (
    echo.
    echo Press any key to close this window ...
    pause >nul
)
exit /b %RC%
