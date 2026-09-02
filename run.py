#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速启动入口：python run.py 直接启动 Web 面板"""
import os
import sys

_base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _base_dir)
# 加载本地依赖（离线可用，无需 pip install）
_libs_dir = os.path.join(_base_dir, 'libs')
if os.path.isdir(_libs_dir):
    sys.path.insert(0, _libs_dir)

if __name__ == "__main__":
    from web.app import run
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run(port=port)
