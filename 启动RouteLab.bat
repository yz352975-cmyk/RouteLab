@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 RouteLab.py %*
) else (
    python RouteLab.py %*
)
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo RouteLab failed. Install Python 3.10+ with Tcl/Tk, or run from cmd to see the error.
    pause
)
