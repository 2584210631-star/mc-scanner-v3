@echo off
cd /d "%~dp0"
color 0C
cls

echo ========================================
echo   MC Scanner - Debug Mode
echo ========================================
echo.

echo [1] Checking Python...
where python
if errorlevel 1 (
    echo [ERROR] Python not found in PATH
    echo.
    echo Please install Python 3.10+ and check "Add Python to PATH"
    echo Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
echo [OK] Python found

echo.
echo [2] Python version:
python --version

REM Version: single source of truth is config.__version__
set MCVER=unknown
for /f "delims=" %%v in ('python -c "import config;print(config.__version__)" 2^>nul') do set MCVER=%%v
title MC Scanner v%MCVER% - Debug Mode

echo.
echo [3] Current directory:
cd

echo.
echo [4] Checking files...
if exist run.py (echo [OK] run.py) else (echo [MISSING] run.py)
if exist web\app.py (echo [OK] web\app.py) else (echo [MISSING] web\app.py)
if exist core\bot.py (echo [OK] core\bot.py) else (echo [MISSING] core\bot.py)

echo.
echo [5] Testing Python import...
python -c "import sys; sys.path.insert(0,'.'); from web.app import app; print('[OK] Web app imported successfully')"
if errorlevel 1 (
    echo [ERROR] Import failed! See error above.
    echo.
    pause
    exit /b 1
)

echo.
echo [6] Starting Web Panel on http://127.0.0.1:8080 ...
echo.
python run.py 8080

echo.
echo [*] Server stopped
pause
