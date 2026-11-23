@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 verify.py %*
) else (
    python verify.py %*
)
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Tests failed. See reports/test_output.txt.
    pause
)
pause
