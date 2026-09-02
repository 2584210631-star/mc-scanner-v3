@echo off
cd /d "%~dp0"
title MC Scanner v3-3.1 - Debug Mode
color 0C
cls

echo ========================================
echo   MC Scanner v3-3.1 - Debug Mode
echo ========================================
echo.

echo [1] Checking Python...
where python
if errorlevel 1 (
    echo [ERROR] Python not found in PATH
    echo.
    echo Please install Python 3.8+ and check "Add Python to PATH"
    echo Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
echo [OK] Python found

echo.
echo [2] Python version:
python --version

echo.
echo [3] Current directory:
cd

echo.
echo [4] Checking files...
if exist run.py (echo [OK] run.py) else (echo [MISSING] run.py)
if exist web\app.py (echo [OK] web\app.py) else (echo [MISSING] web\app.py)
if exist core\bot.py (echo [OK] core\bot.py) else (echo [MISSING] core\bot.py)
if exist libs\flask\__init__.py (echo [OK] libs\flask) else (echo [MISSING] libs\flask)

echo.
echo [5] Testing Python import...
python -c "import sys; sys.path.insert(0,'.'); sys.path.insert(0,'./libs'); from web.app import app; print('[OK] Web app imported successfully')"
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
