@echo off
cd /d "%~dp0"
color 0A
cls

REM Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo.
    echo Please install Python 3.10 or higher:
    echo   Download: https://www.python.org/downloads/
    echo   Check "Add Python to PATH" during installation
    echo.
    pause
    exit /b 1
)

REM Version: single source of truth is config.__version__
set MCVER=unknown
for /f "delims=" %%v in ('python -c "import config;print(config.__version__)" 2^>nul') do set MCVER=%%v
title MC Scanner v%MCVER%

echo ========================================
echo   MC Scanner v%MCVER% - Web Control Panel
echo ========================================
echo.

REM Show Python version
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [*] Python: %PYVER%

REM Check dependencies. libs/ is no longer shipped, so test the real import
REM instead of looking for libs\flask\__init__.py (that path never existed -> always reinstalled, and only flask was installed, pycryptodome missing).
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [!] Missing dependencies, installing from requirements.txt...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
)

echo [*] Starting Web Panel...
echo [*] Browser will open: http://127.0.0.1:8080
echo [*] Close this window to stop the server
echo.
echo ========================================
echo.

REM Open browser after 2 seconds
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8080"

REM Start Web Panel
python run.py 8080

echo.
echo [*] Server stopped
pause
