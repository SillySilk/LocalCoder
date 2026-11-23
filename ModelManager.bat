@echo off
REM Models are now managed by Engine Manager (the shared AI engine for all apps).
if not exist "C:\AI\EngineManager\EngineManager.bat" (
    echo Engine Manager not found at C:\AI\EngineManager
    pause
    exit /b 1
)
call "C:\AI\EngineManager\EngineManager.bat"
