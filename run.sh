#!/bin/bash
cd "$(dirname "$0")"

echo "========================================"
echo "  MC Scanner v3.3.2 - Web 控制面板"
echo "========================================"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[!] 未找到 Python3，请先安装 Python 3.8+"
    echo "    Ubuntu/Debian: sudo apt install python3"
    echo "    CentOS/RHEL:  sudo yum install python3"
    echo "    Mac:         brew install python3"
    exit 1
fi

PYVER=$(python3 --version 2>&1)
echo "[*] $PYVER"

# 检查本地依赖（libs 目录，离线可用）
if [ ! -d "libs/flask" ]; then
    echo "[!] 缺少本地依赖，正在安装 flask..."
    pip3 install flask --quiet 2>/dev/null || pip install flask --quiet
    if [ $? -ne 0 ]; then
        echo "[ERROR] 依赖安装失败，请手动执行: pip3 install flask"
        exit 1
    fi
fi

# 可选加速依赖提示
if ! python3 -c "import uvloop" 2>/dev/null; then
    echo "[i] 提示: 安装 uvloop 可提升异步扫描速度: pip3 install uvloop"
fi

PORT="${1:-8080}"
echo "[*] 启动 Web 面板..."
echo "[*] 浏览器打开 http://127.0.0.1:$PORT"
echo "[*] 关闭此窗口停止服务"
echo ""
echo "========================================"
echo ""

# 延迟后打开浏览器（Linux/Mac）
(sleep 2 && (xdg-open "http://127.0.0.1:$PORT" 2>/dev/null || open "http://127.0.0.1:$PORT" 2>/dev/null)) &

python3 run.py "$PORT"

echo ""
echo "[*] 服务已停止"
