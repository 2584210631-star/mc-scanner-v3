#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速启动入口：python run.py [port] 直接启动 Web 面板"""
import os
import sys

_base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _base_dir)

# release 包自带依赖时自动加载（源码仓库无 libs/ 时走 pip 安装的依赖）
_libs_dir = os.path.join(_base_dir, 'libs')
if os.path.isdir(_libs_dir):
    sys.path.insert(0, _libs_dir)

if __name__ == "__main__":
    try:
        import flask  # noqa: F401
    except ImportError:
        print("[!] 缺少 flask，请先安装依赖：pip install -r requirements.txt")
        sys.exit(1)

    from web.app import run
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run(port=port)
