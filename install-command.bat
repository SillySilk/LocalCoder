@echo off
setlocal
REM Creates a terminal command that opens one of this folder's launchers.
REM Usage: install-command.bat [name] [launcher]
REM   install-command.bat                          -> george opens LocalCoder.bat
REM   install-command.bat models ModelManager.bat  -> models opens Model Manager
set "NAME=%~1"
if "%NAME%"=="" set "NAME=george"
set "TARGET=%~2"
if "%TARGET%"=="" set "TARGET=LocalCoder.bat"
if not exist "%~dp0%TARGET%" (
    echo No launcher called %TARGET% in %~dp0
    exit /b 1
)
set "BIN=%USERPROFILE%\.local\bin"
if not exist "%BIN%\" mkdir "%BIN%"
(
    echo @echo off
    echo REM Opens %TARGET% from LocalCoder in the current folder.
    echo call "%~dp0%TARGET%" %%*
) > "%BIN%\%NAME%.cmd"
echo Created "%BIN%\%NAME%.cmd"
echo %PATH% | "%SystemRoot%\System32\find.exe" /i "%BIN%" >nul || echo Note: add "%BIN%" to your PATH so Windows can find it.
echo Open a new terminal and type: %NAME%
endlocal
