#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速启动入口：python run.py 直接启动 Web 面板"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    from web.app import run
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run(port=port)
