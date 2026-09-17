# -*- coding: utf-8 -*-
"""Web 控制面板：优先拆分模块，缺模块时回退完整版下载。"""
import os
import sys
import logging
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import logger

logging.getLogger("werkzeug").setLevel(logging.WARNING)

_DIR = os.path.dirname(os.path.abspath(__file__))
_FULL = os.path.join(_DIR, "_app_full.py")
_GOOD_URL = (
    "https://raw.githubusercontent.com/2584210631-star/mc-scanner-v3/"
    "1203edda6e31b1a43725e09a484974d88044d517/web/app.py"
)

def _try_expand():
    try:
        from web._expand_packs import expand
        expand(force=False)
    except Exception:
        try:
            from _expand_packs import expand  # type: ignore
            expand(force=False)
        except Exception:
            pass

def _has_split():
    need = ["state.py", "routes_core.py", "routes_scan.py", "routes_ai.py", "services_scan.py"]
    return all(os.path.isfile(os.path.join(_DIR, n)) for n in need)

def _run_split():
    from flask import Flask, request, jsonify
    try:
        from web import state
    except ImportError:
        import state  # type: ignore
    app = Flask(__name__)
    try:
        app.json.ensure_ascii = False
    except AttributeError:
        app.config["JSON_AS_ASCII"] = False
    @app.before_request
    def _check_token():
        token = state.get_web_token()
        if not token:
            return None
        if request.path == "/" or request.path.startswith("/static/"):
            return None
        if request.path.startswith("/api/"):
            client_token = request.headers.get("X-API-Token", "") or request.args.get("token", "")
            if client_token != token:
                return jsonify({"error": "未授权访问"}), 401
        return None
    modules = [
        "routes_core", "routes_scan", "routes_scan_extra", "routes_warn",
        "routes_data", "routes_ai", "routes_ai_bots", "routes_observer",
        "routes_config", "routes_ops", "routes_tools",
    ]
    for name in modules:
        try:
            if __package__:
                mod = __import__(f"{__package__}.{name}", fromlist=["register"])
            else:
                mod = __import__(name, fromlist=["register"])
            mod.register(app)
            logger.info(f"[web] registered {name}")
        except Exception as e:
            logger.warning(f"[web] skip {name}: {e}")
    def run(db_path="mcscanner.db", port=8080, host="127.0.0.1"):
        logger.setup_logger()
        from storage import db
        db.init_db(db_path)
        logger.info(f"[*] Web (split) http://{host}:{port}")
        app.run(host=host, port=port, debug=False, threaded=True)
    globals()["app"] = app
    globals()["run"] = run

def _run_monolith():
    if not (os.path.isfile(_FULL) and os.path.getsize(_FULL) > 50000):
        logger.info("[web] downloading full app.py fallback...")
        with urllib.request.urlopen(_GOOD_URL, timeout=45) as resp:
            data = resp.read().decode("utf-8")
        old = "@app.route('/')\ndef index():\n    return send_from_directory(os.path.dirname(__file__), 'index.html')\n"
        new = (
            "@app.route('/')\ndef index():\n"
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
    with open(_FULL, "r", encoding="utf-8") as f:
        code = compile(f.read(), _FULL, "exec")
    exec(code, globals())

_try_expand()
if _has_split():
    try:
        _run_split()
        logger.info("[web] using split route modules")
    except Exception as e:
        logger.warning(f"[web] split failed ({e}), fallback monolith")
        _run_monolith()
else:
    logger.info("[web] split incomplete, using monolith fallback")
    _run_monolith()
