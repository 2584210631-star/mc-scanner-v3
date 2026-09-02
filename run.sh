#!/bin/bash
echo "========================================"
echo "  MC Scanner v3Pro - Web 控制面板"
echo "========================================"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[!] 未找到 Python3，请先安装 Python 3.8+"
    exit 1
fi

# 检查依赖
if ! python3 -c "import flask" &> /dev/null; then
    echo "[*] 安装依赖..."
    pip3 install -r requirements.txt
fi

echo "[*] 启动 Web 面板..."
echo "[*] 浏览器打开 http://127.0.0.1:8080"
echo ""
python3 cli.py web --port 8080
