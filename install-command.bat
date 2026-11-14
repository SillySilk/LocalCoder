@echo off
setlocal
REM Creates a terminal command (default: george) that opens LocalCoder in the
REM current folder. Usage: install-command.bat [name]
set "NAME=%~1"
if "%NAME%"=="" set "NAME=george"
set "BIN=%USERPROFILE%\.local\bin"
if not exist "%BIN%\" mkdir "%BIN%"
(
    echo @echo off
    echo REM Opens LocalCoder ^(local models in Claude Code / OpenCode^) in the current folder.
    echo call "%~dp0LocalCoder.bat" %%*
) > "%BIN%\%NAME%.cmd"
echo Created "%BIN%\%NAME%.cmd"
echo %PATH% | "%SystemRoot%\System32\find.exe" /i "%BIN%" >nul || echo Note: add "%BIN%" to your PATH so Windows can find it.
echo Open a new terminal and type: %NAME%
endlocal
