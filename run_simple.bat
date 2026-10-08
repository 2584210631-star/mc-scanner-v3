@echo off
cd /d "%~dp0"

REM 版本号单一来源：config.__version__
set MCVER=unknown
for /f "delims=" %%v in ('python -c "import config;print(config.__version__)" 2^>nul') do set MCVER=%%v
title MC Scanner v%MCVER%

echo Starting MC Scanner v%MCVER%...
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found! Please install Python 3.10+
    echo Download: https://www.python.org/downloads/
    echo Check "Add Python to PATH" during install
    pause
    exit /b 1
)

python run.py 8080

pause
