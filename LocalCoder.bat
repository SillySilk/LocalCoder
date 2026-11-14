@echo off
setlocal EnableDelayedExpansion
title LocalCoder - local models in Claude Code / OpenCode

REM ---- Project folder: argument (Send To / drag-drop / george), else ask ----
set "WORKDIR=%~1"
if not "%WORKDIR%"=="" goto :have_dir
set "WORKDIR=%CD%"
if /i "%CD%\"=="%~dp0" (
    echo.
    set /p "WORKDIR=Project folder to work in [%CD%]: "
    if "!WORKDIR!"=="" set "WORKDIR=%CD%"
)
:have_dir

where python >nul 2>&1
if errorlevel 1 (
    echo LocalCoder needs Python 3. Install it from https://www.python.org and try again.
    pause
    exit /b 1
)

python "%~dp0lc_launch.py" "%WORKDIR%" %2 %3 %4 %5 %6 %7 %8 %9
if errorlevel 1 pause
endlocal
