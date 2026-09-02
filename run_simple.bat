@echo off
cd /d "%~dp0"
title MC Scanner v3

echo Starting MC Scanner v3...
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found! Please install Python 3.8+
    echo Download: https://www.python.org/downloads/
    echo Check "Add Python to PATH" during install
    pause
    exit /b 1
)

python run.py 8080

pause
