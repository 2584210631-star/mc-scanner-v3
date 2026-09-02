@echo off
title MC Scanner v3
color 0A
cls

echo ========================================
echo   MC Scanner v3 - Web Control Panel
echo ========================================
echo.

REM Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo.
    echo Please install Python 3.8 or higher:
    echo   Download: https://www.python.org/downloads/
    echo   Check "Add Python to PATH" during installation
    echo.
    pause
    exit /b 1
)

REM Show Python version
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [*] Python: %PYVER%

REM Check local dependencies
if not exist "libs\flask\__init__.py" (
    echo [!] Missing libs directory, installing dependencies...
    pip install flask -i https://pypi.tuna.tsinghua.edu.cn/simple
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
