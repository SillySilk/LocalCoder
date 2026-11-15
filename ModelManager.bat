@echo off
setlocal
title Model Manager - Ollama models for George

where python >nul 2>&1
if errorlevel 1 (
    echo Model Manager needs Python 3. Install it from https://www.python.org and try again.
    pause
    exit /b 1
)

python "%~dp0mm.py" %*
if errorlevel 1 pause
endlocal
