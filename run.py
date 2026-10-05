#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速启动入口：python run.py 直接启动 Web 面板"""
import os
import sys
import subprocess

_base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _base_dir)

# 加载本地依赖（离线可用，无需 pip install）
_libs_dir = os.path.join(_base_dir, 'libs')
if os.path.isdir(_libs_dir):
    sys.path.insert(0, _libs_dir)


if __name__ == "__main__":
    # 确保核心依赖 flask
    try:
        import flask  # noqa: F401
    except ImportError:
        print("[!] 缺少 flask，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "--quiet"])

    # 可选加速依赖（uvloop/pysimdjson）：用户自行 pip install，代码自动降级
    for _pkg in ("uvloop", "simdjson"):
        try:
            __import__(_pkg)
        except Exception:
            pass

    from web.app import run
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run(port=port)
