#!/bin/bash
echo "========================================"
echo "  MC Scanner v3 - Web 控制面板"
echo "========================================"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[!] 未找到 Python3，请先安装 Python 3.8+"
    exit 1
fi

echo "[*] 启动 Web 面板..."
echo "[*] 浏览器打开 http://127.0.0.1:8080"
echo ""

# 延迟后打开浏览器
(sleep 2 && xdg-open http://127.0.0.1:8080 2>/dev/null || open http://127.0.0.1:8080 2>/dev/null) &

python3 run.py 8080
