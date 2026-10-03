@echo off
rem ==========================================================================
rem  sim.bat  -  One-click Verilog compile / simulate / view waveform
rem  Requires: Icarus Verilog (iverilog + vvp)  +  GTKWave
rem  Usage:    double-click it, or run:  sim.bat -h
rem
rem  NOTE: this file is intentionally pure ASCII. cmd.exe mis-parses batch
rem  files that contain non-ASCII bytes when the console code page is UTF-8.
rem ==========================================================================
setlocal EnableExtensions EnableDelayedExpansion
set "SIM_VER=1.0"
title Verilog Simulator (iverilog + GTKWave)

rem ------------------------- defaults ---------------------------------------
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "WORKDIR="
set "TOP="
set "VCDOPT="
set "NOWAVE=0"
set "NOSIG=0"
set "ONLYWAVE=0"
set "NOPAUSE=0"
set "WALL=0"
set "ASK_VER="

rem ------------------------- parse arguments --------------------------------
:parse
if "%~1"=="" goto parse_done
set "ARG=%~1"
if /i "!ARG!"=="-h"        goto usage
if /i "!ARG!"=="--help"    goto usage
if /i "!ARG!"=="/?"        goto usage
if /i "!ARG!"=="-V"        ( set "ASK_VER=1"  & shift & goto parse )
if /i "!ARG!"=="--version" ( set "ASK_VER=1"  & shift & goto parse )
if /i "!ARG!"=="-t"        goto a_top
if /i "!ARG!"=="-d"        goto a_dir
if /i "!ARG!"=="-w"        goto a_wave
if /i "!ARG!"=="-n"        ( set "NOWAVE=1"   & shift & goto parse )
if /i "!ARG!"=="-c"        ( set "NOSIG=1"    & shift & goto parse )
if /i "!ARG!"=="-o"        ( set "ONLYWAVE=1" & shift & goto parse )
if /i "!ARG!"=="-q"        ( set "NOPAUSE=1"  & shift & goto parse )
if /i "!ARG!"=="-W"        ( set "WALL=1"     & shift & goto parse )
if "!ARG:~0,1!"=="-" (
    echo [ERROR] unknown option: !ARG!
    echo         run "sim.bat -h" for help
    set "RC=1"
    goto finish
)
rem a bare word is taken as the top-level module name
set "TOP=!ARG!"
shift
goto parse

:a_top
if "%~2"=="" (
    echo [ERROR] -t needs a module name
    set "RC=1"
    goto finish
)
set "TOP=%~2"
shift
shift
goto parse

:a_dir
if "%~2"=="" (
    echo [ERROR] -d needs a directory
    set "RC=1"
    goto finish
)
set "WORKDIR=%~2"
shift
shift
goto parse

:a_wave
if "%~2"=="" (
    echo [ERROR] -w needs a file name
    set "RC=1"
    goto finish
)
set "VCDOPT=%~2"
shift
shift
goto parse

:parse_done
if defined WORKDIR if "!WORKDIR:~-1!"=="\" set "WORKDIR=!WORKDIR:~0,-1!"
rem make it absolute, so that paths stay valid after pushd
if defined WORKDIR for %%d in ("!WORKDIR!") do set "WORKDIR=%%~fd"

rem ------------------------- locate the tools -------------------------------
set "IVERILOG="
set "VVP="
set "GTKWAVE="
for /f "delims=" %%p in ('where iverilog 2^>nul') do if not defined IVERILOG set "IVERILOG=%%p"
for /f "delims=" %%p in ('where vvp 2^>nul')      do if not defined VVP      set "VVP=%%p"
for /f "delims=" %%p in ('where gtkwave 2^>nul')  do if not defined GTKWAVE set "GTKWAVE=%%p"
rem not in PATH? try the usual install location
if not defined IVERILOG if exist "C:\iverilog\bin\iverilog.exe" (
    set "PATH=C:\iverilog\bin;!PATH!"
    set "IVERILOG=C:\iverilog\bin\iverilog.exe"
    set "VVP=C:\iverilog\bin\vvp.exe"
    if exist "C:\iverilog\bin\gtkwave.exe" set "GTKWAVE=C:\iverilog\bin\gtkwave.exe"
)
if not defined IVERILOG (
    echo [ERROR] iverilog.exe not found
    echo         install Icarus Verilog and add its bin directory to PATH
    set "RC=1"
    goto finish
)
if not defined VVP (
    echo [ERROR] vvp.exe not found
    set "RC=1"
    goto finish
)

if defined ASK_VER (
    echo.
    echo   tool check
    echo   ------------------------------------------------------------
    echo   iverilog : !IVERILOG!
    "!IVERILOG!" -V 2>&1 | findstr /b /c:"Icarus"
    if defined GTKWAVE (
        echo   gtkwave  : !GTKWAVE!
        "!GTKWAVE!" -V
    ) else (
        echo   gtkwave  : not found
    )
    set "RC=0"
    goto finish
)

rem ------------------------- pick the working directory ---------------------
if not defined WORKDIR (
    set "WORKDIR=%CD%"
    if not exist "!WORKDIR!\*.v" if not exist "!WORKDIR!\*.sv" set "WORKDIR=!SCRIPT_DIR!"
)
if not exist "!WORKDIR!\" (
    echo [ERROR] directory not found: !WORKDIR!
    set "RC=1"
    goto finish
)
pushd "!WORKDIR!"
if errorlevel 1 (
    echo [ERROR] cannot enter directory: !WORKDIR!
    set "RC=1"
    goto finish
)
set "PUSHED=1"
echo.
echo   Verilog one-click sim   ^|   dir: !WORKDIR!

rem build artefacts live in <workdir>\.sim
set "OUTDIR=!WORKDIR!\.sim"
set "OUT=!OUTDIR!\sim.vvp"
set "TCL=!OUTDIR!\auto_signals.tcl"

rem ======================= 1) collect source files ==========================
set "SRCS="
set "NSRC=0"
for /f "delims=" %%f in ('dir /b /a-d /on "*.v" "*.sv" 2^>nul') do (
    set "SRCS=!SRCS! "%%f""
    set /a NSRC+=1
)

if "%ONLYWAVE%"=="1" goto pick_vcd

if !NSRC!==0 (
    echo.
    echo [ERROR] no .v / .sv source files here
    echo         use:  sim.bat -d YOUR_DESIGN_DIR
    set "RC=1"
    goto finish
)

rem ======================= 2) find the top-level module =====================
if not defined TOP (
    set "TBFILE="
    for %%p in (tb_*.v *_tb.v *_test.v tb_*.sv *_tb.sv *_test.sv) do (
        if not defined TBFILE if exist "%%p" set "TBFILE=%%p"
    )
    if defined TBFILE (
        call :module_of "!TBFILE!"
        if defined MODNAME set "TOP=!MODNAME!"
    ) else if !NSRC!==1 (
        for %%f in ("*.v" "*.sv") do if not defined MODNAME call :module_of "%%f"
        if defined MODNAME set "TOP=!MODNAME!"
    )
)

rem ======================= 3) compile ======================================
if not exist "!OUTDIR!\" mkdir "!OUTDIR!" >nul 2>nul
set "FLAGS=%IVERILOG_FLAGS%"
if "%WALL%"=="1" set "FLAGS=!FLAGS! -Wall"
set "HAS_S="
if defined TOP set "HAS_S=-s !TOP!"

echo.
echo   [1/3] compiling  (!NSRC! source file^(s^))
if defined TOP (
    echo         top module : !TOP!
) else (
    echo         top module : auto ^(let iverilog decide^)
)
rem NOTE: iverilog on Windows takes every argument after a file name as a file
rem name, so all options must come first.
iverilog -g2012 !HAS_S! !FLAGS! -o "!OUT!" !SRCS!
if errorlevel 1 (
    echo.
    echo [FAILED] compile error, fix the code and run again
    set "RC=1"
    goto finish
)

rem ======================= 4) simulate =====================================
echo.
echo   [2/3] simulating
vvp "!OUT!"
if errorlevel 1 (
    echo.
    echo [FAILED] simulation error ^(vvp returned non-zero^)
    set "RC=1"
    goto finish
)

rem ======================= 5) find the waveform file =======================
:pick_vcd
set "VCD="
if defined VCDOPT (
    if exist "!VCDOPT!" (
        set "VCD=!VCDOPT!"
    ) else (
        echo [WARN] waveform file not found: !VCDOPT!
        echo        falling back to the newest .vcd
    )
)
if not defined VCD (
    for /f "delims=" %%f in ('dir /b /a-d /o-d "*.vcd" 2^>nul') do (
        set "VCD=%%f"
        goto vcd_found
    )
)
:vcd_found
if not defined VCD (
    echo.
    echo [WARN] no .vcd waveform file found
    echo        does your testbench have $dumpfile^("dump.vcd"^) and $dumpvars ?
    set "RC=0"
    goto finish
)
set "VCD_TS="
set "VCD_SZ=0"
for %%f in ("!VCD!") do (
    set "VCD_TS=%%~tf"
    set "VCD_SZ=%%~zf"
)
echo.
echo         waveform   : !VCD!
echo         modified   : !VCD_TS!   size: !VCD_SZ! bytes

rem the .vvp is always rewritten by the compile step just before the simulation,
rem so a waveform older than it cannot come from this run.  (timestamps are
rem minute-resolution, so a same-minute waveform is never reported.)
if "%ONLYWAVE%"=="0" if defined VCD_TS (
    set "VVP_TS="
    for %%f in ("!OUT!") do set "VVP_TS=%%~tf"
    if defined VVP_TS if "!VCD_TS!" LSS "!VVP_TS!" (
        echo [WARN] this waveform is older than the current build, it may be stale
        echo        check that the testbench has $dumpvars, or pick one with -w
    )
)

if "%NOWAVE%"=="1" (
    echo   [3/3] skipped opening GTKWave ^(-n^)
    set "RC=0"
    goto finish
)

rem ======================= 6) open the waveform ============================
if not defined GTKWAVE (
    echo.
    echo [WARN] gtkwave.exe not found, cannot show the waveform
    set "RC=0"
    goto finish
)

set "VCD_FULL=!WORKDIR!\!VCD!"
set "GKW="
for %%f in ("!VCD!") do set "GKW=!WORKDIR!\%%~nf.gtkw"

if exist "!GKW!" (
    echo   [3/3] opening GTKWave with saved layout: !GKW!
    echo         delete that file to go back to listing every signal
    start "" "!GTKWAVE!" -f "!VCD_FULL!" -a "!GKW!"
) else if "%NOSIG%"=="1" (
    echo   [3/3] opening GTKWave
    start "" "!GTKWAVE!" -f "!VCD_FULL!"
) else (
    echo   [3/3] opening GTKWave, adding all signals automatically
    call :write_tcl
    start "" "!GTKWAVE!" -f "!VCD_FULL!" -S "!TCL!"
)
set "RC=0"
goto finish

rem ======================= subroutines =====================================

:module_of
rem take the first "module <name>" found in file %~1, result in MODNAME
set "MODNAME="
set "M="
for /f "tokens=2" %%m in ('findstr /r /i /c:"^ *module " "%~1" 2^>nul') do if not defined M set "M=%%m"
if defined M (
    set "M=!M:#=!"
    for /f "tokens=1 delims=;#( " %%x in ("!M!") do set "MODNAME=%%x"
)
exit /b 0

:write_tcl
rem Generate a GTKWave Tcl script that puts every signal of the dumpfile into
rem the wave window.  It uses GTKWave's own signal database, so it works for
rem any dumpfile and skips $var parameters.
if not exist "!OUTDIR!\" mkdir "!OUTDIR!" >nul 2>nul
> "!TCL!" echo # auto-generated by sim.bat - add every signal of the dumpfile
>> "!TCL!" echo set __sim_sigs {}
>> "!TCL!" echo set __sim_n [gtkwave::getNumFacs]
>> "!TCL!" echo set __sim_i 0
>> "!TCL!" echo while {$__sim_i ne $__sim_n} {
>> "!TCL!" echo     set __sim_vt ""
>> "!TCL!" echo     catch {set __sim_vt [gtkwave::getFacVtype $__sim_i]}
>> "!TCL!" echo     if {[string match "parm*" $__sim_vt]} {
>> "!TCL!" echo         incr __sim_i
>> "!TCL!" echo         continue
>> "!TCL!" echo     }
>> "!TCL!" echo     lappend __sim_sigs [gtkwave::getFacName $__sim_i]
>> "!TCL!" echo     incr __sim_i
>> "!TCL!" echo }
>> "!TCL!" echo if {[llength $__sim_sigs]} {
>> "!TCL!" echo     catch {gtkwave::addSignalsFromList $__sim_sigs}
>> "!TCL!" echo }
>> "!TCL!" echo catch {gtkwave::/Time/Zoom/Zoom_Full}
exit /b 0

:usage
echo.
echo   sim_batch_only.bat v%SIM_VER% - pure batch version (no Python needed)
echo                    one-click Verilog compile / simulate / view waveform
echo                    iverilog + vvp + GTKWave
echo.
echo   NOTE: the recommended entry point is sim.bat, which runs sim.py and has
echo         a few extras (--list, -r, --sig-exclude, --tb-only, --fix-bom).
echo.
echo   usage:
echo     sim_batch_only.bat [options] [top_module]
echo.
echo   common:
echo     sim.bat                  compile all .v/.sv here, simulate, open waves
echo     sim.bat tb_counter       compile with this top module (testbench)
echo     sim.bat -d src           work in another directory
echo     sim.bat -o               open the waveform only, do not recompile
echo.
echo   options:
echo     -t ^<module^>   top-level module
echo     -d ^<dir^>      design directory ^(default: current dir, else script dir^)
echo     -w ^<file^>     waveform file to open ^(default: newest .vcd^)
echo     -n            compile + simulate only, do not open GTKWave
echo     -o            do not compile, just open an existing waveform
echo     -c            do not auto-add signals ^(only reuse an existing .gtkw^)
echo     -W            enable compile warnings ^(-Wall^)
echo     -q            do not pause at the end
echo     -V            show iverilog / gtkwave versions and exit
echo     -h            show this help
echo.
echo   notes:
echo     * waveforms come from $dumpfile^("dump.vcd"^) + $dumpvars in the testbench
echo     * the first run adds every signal; arrange them in GTKWave, then use
echo       File -^> Write Save File to store a .gtkw that is reused next time
echo     * extra iverilog flags:  set IVERILOG_FLAGS=-Wall   before running
echo     * sources are collected flat, sub-directories are not searched
echo.
set "RC=0"
goto finish

rem ======================= wrap up =========================================
:finish
if defined PUSHED popd
if "%NOPAUSE%"=="1" exit /b %RC%
rem launched by double-click?  then the console would vanish instantly, so wait
set "CMDLINE=%cmdcmdline%"
if defined CMDLINE set "CMDLINE=%CMDLINE:"=%"
if not "!CMDLINE:%~nx0=!"=="!CMDLINE!" (
    echo.
    echo Press any key to close this window ...
    pause >nul
)
exit /b %RC%
