@echo off
chcp 65001 >nul
echo ========================================
echo   MC Scanner v3Pro - Web 控制面板
echo ========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [!] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

REM 检查依赖
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [*] 安装依赖...
    pip install -r requirements.txt
)

echo [*] 启动 Web 面板...
echo [*] 浏览器打开 http://127.0.0.1:8080
echo.
python cli.py web --port 8080
pause
