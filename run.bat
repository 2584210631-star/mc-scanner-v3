@echo off
chcp 65001 >nul
title MC Scanner v3
echo ========================================
echo   MC Scanner v3 - Web 控制面板
echo ========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [!] 未找到 Python，请先安装 Python 3.8+
    echo     下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [*] 启动 Web 面板...
echo [*] 浏览器自动打开 http://127.0.0.1:8080
echo [*] 按 Ctrl+C 停止
echo.

REM 延迟1秒后打开浏览器
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8080"

python run.py 8080
pause
