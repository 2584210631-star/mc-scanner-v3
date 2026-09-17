# -*- coding: utf-8 -*-
"""Bootstrap: download known-good web/app.py once, then exec (recovery from accidental truncate)."""
import os
import sys
import urllib.request

_DIR = os.path.dirname(os.path.abspath(__file__))
_FULL = os.path.join(_DIR, "_app_full.py")
# Last commit that still had the complete Flask app module
_GOOD_URL = (
    "https://raw.githubusercontent.com/2584210631-star/mc-scanner-v3/"
    "1203edda6e31b1a43725e09a484974d88044d517/web/app.py"
)

def _ensure_full() -> str:
    if os.path.isfile(_FULL) and os.path.getsize(_FULL) > 50000:
        return _FULL
    # Prefer local chunks if present
    parts = []
    i = 0
    while True:
        p = os.path.join(_DIR, f"app_chunk_{i:02d}.txt")
        if not os.path.isfile(p):
            break
        with open(p, "r", encoding="utf-8") as f:
            parts.append(f.read())
        i += 1
    if parts:
        data = "".join(parts)
    else:
        try:
            with urllib.request.urlopen(_GOOD_URL, timeout=30) as resp:
                data = resp.read().decode("utf-8")
        except Exception as e:
            raise RuntimeError(
                "web/app.py missing and download failed. "
                "Run: git checkout 1203edd -- web/app.py"
            ) from e
    # Hook index() to ui_inject if still plain send_from_directory
    old = (
        "@app.route('/')\n"
        "def index():\n"
        "    return send_from_directory(os.path.dirname(__file__), 'index.html')\n"
    )
    new = (
        "@app.route('/')\n"
        "def index():\n"
        "    import importlib.util\n"
        "    _p = os.path.join(os.path.dirname(__file__), 'ui_inject.py')\n"
        "    _spec = importlib.util.spec_from_file_location('ui_inject', _p)\n"
        "    _mod = importlib.util.module_from_spec(_spec)\n"
        "    _spec.loader.exec_module(_mod)\n"
        "    return _mod.serve_index(os.path.dirname(__file__))\n"
    )
    if old in data:
        data = data.replace(old, new)
    with open(_FULL, "w", encoding="utf-8") as f:
        f.write(data)
    return _FULL

_path = _ensure_full()
with open(_path, "r", encoding="utf-8") as f:
    _code = compile(f.read(), _path, "exec")
exec(_code, globals())
