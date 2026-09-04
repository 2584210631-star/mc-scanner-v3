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


def _ensure_package(pkg_name: str, import_name: str = None) -> bool:
    """检查包是否可导入，不可用则自动 pip 安装。返回是否可用。"""
    import_name = import_name or pkg_name
    try:
        __import__(import_name)
        return True
    except Exception:
        pass
    # C 扩展可能平台不兼容，尝试 pip 安装到用户环境
    try:
        print(f"[i] {pkg_name} 不可用（可能平台不兼容），正在自动安装...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", pkg_name, "--quiet"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        __import__(import_name)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    # 确保核心依赖 flask
    try:
        import flask  # noqa: F401
    except ImportError:
        print("[!] 缺少 flask，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "--quiet"])

    # 可选加速依赖（C 扩展，平台不兼容时自动安装）
    uvloop_ok = _ensure_package("uvloop")
    simdjson_ok = _ensure_package("pysimdjson", "simdjson")
    if uvloop_ok or simdjson_ok:
        accel = []
        if uvloop_ok:
            accel.append("uvloop")
        if simdjson_ok:
            accel.append("pysimdjson")
        print(f"[*] 加速已启用: {', '.join(accel)}")

    from web.app import run
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run(port=port)
