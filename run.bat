@echo off
chcp 65001 >nul
title MC Scanner v3
color 0A
cls

echo ========================================
echo   MC Scanner v3 - Web 控制面板
echo ========================================
echo.

REM 检查 Python
where python >nul 2>&1
if errorlevel 1 (
    echo [!] 未检测到 Python！
    echo.
    echo 请先安装 Python 3.8 或更高版本：
    echo   下载地址: https://www.python.org/downloads/
    echo   安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

REM 显示 Python 版本
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [*] Python 版本: %PYVER%
echo.

REM 检查本地依赖
if not exist "libs\flask\__init__.py" (
    echo [!] 缺少本地依赖 libs 目录
    echo [*] 正在尝试联网安装依赖...
    pip install flask -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [!] 依赖安装失败，请检查网络连接
        pause
        exit /b 1
    )
)

echo [*] 正在启动 Web 面板...
echo [*] 浏览器将自动打开: http://127.0.0.1:8080
echo [*] 关闭此窗口即可停止服务
echo.
echo ========================================
echo.

REM 延迟2秒后打开浏览器
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8080"

REM 启动 Web 面板
python run.py 8080

echo.
echo [*] 服务已停止
pause
