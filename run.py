#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速启动入口：python run.py [port] 直接启动 Web 面板"""
import os
import sys

_base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _base_dir)


def _load_vendored_libs() -> bool:
    """加载 libs/ 里的依赖。C 扩展（.so）是 Linux x86_64 预编译的，
    在 ARM64/Windows 等平台加载失败时自动移除 libs/，降级到系统安装的包。
    返回 True 表示使用 libs/，False 表示已降级。"""
    libs_dir = os.path.join(_base_dir, 'libs')
    if not os.path.isdir(libs_dir):
        return False

    sys.path.insert(0, libs_dir)

    # 纯 Python 包一定能加载，先验证 flask
    try:
        import flask  # noqa: F401
    except ImportError:
        sys.path.remove(libs_dir)
        return False

    # C 扩展包：架构不匹配时会抛 ImportError/OSError
    c_ext_pkgs = ['Crypto', 'cryptography', 'uvloop', 'simdjson', 'cffi']
    for pkg in c_ext_pkgs:
        try:
            __import__(pkg)
        except (ImportError, OSError):
            # 架构不匹配，移除 libs/ 降级到系统包
            sys.path.remove(libs_dir)
            for p in c_ext_pkgs + ['flask']:
                sys.modules.pop(p, None)
            # 清除子模块缓存
            for mod in list(sys.modules.keys()):
                if mod.startswith(tuple(c_ext_pkgs)) or mod.startswith('flask.'):
                    del sys.modules[mod]
            print(f"[i] libs/ 里的 {pkg} 不兼容当前平台，已降级到系统安装的依赖")
            return False
    return True


_load_vendored_libs()

if __name__ == "__main__":
    try:
        import flask  # noqa: F401
    except ImportError:
        print("[!] 缺少 flask，请先安装依赖：pip install -r requirements.txt")
        sys.exit(1)
    try:
        import Crypto  # noqa: F401
    except ImportError:
        print("[!] 缺少 pycryptodome，请安装：pip install pycryptodome")
        sys.exit(1)

    from web.app import run
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run(port=port)
