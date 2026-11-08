@echo off
setlocal EnableDelayedExpansion
title LocalCoder - local models in Claude Code / OpenCode

REM ---- Project folder: argument (Send To / drag-drop), else ask ----
set "WORKDIR=%~1"
if not "%WORKDIR%"=="" goto :have_dir
set "WORKDIR=%CD%"
if /i "%CD%\"=="%~dp0" (
    echo.
    set /p "WORKDIR=Project folder to work in [%CD%]: "
    if "!WORKDIR!"=="" set "WORKDIR=%CD%"
)
:have_dir
if not exist "%WORKDIR%\" (
    echo Folder not found: "%WORKDIR%"
    pause
    exit /b 1
)

REM ---- Make sure Ollama is running ----
ollama list >nul 2>&1
if errorlevel 1 (
    echo Starting Ollama...
    start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
    for /l %%i in (1,1,30) do (
        ollama list >nul 2>&1 && goto :ollama_up
        timeout /t 1 /nobreak >nul
    )
    echo Ollama did not start. Open the Ollama app and try again.
    pause
    exit /b 1
)
:ollama_up

REM ---- Model menu (coding variants with big memory listed first) ----
set /a N=0
for /f "skip=1 tokens=1" %%m in ('ollama list') do (
    echo %%m | findstr /r /c:"-64k" /c:"-32k" >nul && (
        set /a N+=1
        set "M!N!=%%m"
    )
)
set /a FIRST_OTHER=N+1
for /f "skip=1 tokens=1" %%m in ('ollama list') do (
    echo %%m | findstr /r /c:"-64k" /c:"-32k" >nul || (
        set /a N+=1
        set "M!N!=%%m"
    )
)
if %N%==0 (
    echo No models installed. Run: ollama pull devstral
    pause
    exit /b 1
)

echo.
echo ===== Pick a model =====
for /l %%i in (1,1,%N%) do (
    if %%i==%FIRST_OTHER% echo   --- other models ^(default memory, may forget on long tasks^) ---
    echo   %%i^) !M%%i!
)
echo.
set "PICK="
set /p "PICK=Model number [1]: "
if "%PICK%"=="" set "PICK=1"
set "MODEL=!M%PICK%!"
if "%MODEL%"=="" (
    echo Invalid choice.
    pause
    exit /b 1
)

echo.
echo ===== Pick a tool =====
echo   1^) Claude Code  ^(keeps your hooks, skills, CLAUDE.md^)
echo   2^) OpenCode
set "TOOL="
set /p "TOOL=Tool number [1]: "
if "%TOOL%"=="" set "TOOL=1"
set "INTEGRATION="
if "%TOOL%"=="1" set "INTEGRATION=claude"
if "%TOOL%"=="2" set "INTEGRATION=opencode"
if "%INTEGRATION%"=="" (
    echo Invalid choice.
    pause
    exit /b 1
)

REM ---- Claude Code: map every internal model slot to the local pick and
REM ---- compact before the model's real memory runs out (window-local only)
if "%INTEGRATION%"=="claude" (
    set "ANTHROPIC_DEFAULT_OPUS_MODEL=%MODEL%"
    set "ANTHROPIC_DEFAULT_SONNET_MODEL=%MODEL%"
    set "ANTHROPIC_DEFAULT_HAIKU_MODEL=%MODEL%"
    set "ANTHROPIC_DEFAULT_FABLE_MODEL=%MODEL%"
    set "CLAUDE_CODE_SUBAGENT_MODEL=%MODEL%"
    set "CLAUDE_CODE_MAX_OUTPUT_TOKENS=8192"
    set "CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536"
    echo %MODEL% | findstr /c:"-32k" >nul && set "CLAUDE_CODE_MAX_CONTEXT_TOKENS=32768"
)

echo.
echo Launching %INTEGRATION% with %MODEL% in "%WORKDIR%"
echo.
cd /d "%WORKDIR%"
ollama launch %INTEGRATION% --model %MODEL%
endlocal
