# -*- coding: utf-8 -*-
"""Web 控制面板（拆分路由版）。"""
import os
import sys
import logging
from flask import Flask, request, jsonify

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import logger

logging.getLogger("werkzeug").setLevel(logging.WARNING)

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
            return jsonify({"error": "未授权访问，请配置正确的API Token"}), 401
    return None


def _register_routes():
    modules = [
        "routes_core", "routes_scan", "routes_scan_extra", "routes_warn",
        "routes_data", "routes_ai", "routes_ai_bots", "routes_observer",
        "routes_config", "routes_ops", "routes_tools",
    ]
    for name in modules:
        if __package__:
            mod = __import__(f"{__package__}.{name}", fromlist=["register"])
        else:
            mod = __import__(name, fromlist=["register"])
        mod.register(app)
        logger.info(f"[web] registered {name}")


_register_routes()


def run(db_path: str = "mcscanner.db", port: int = 8080, host: str = "127.0.0.1"):
    logger.setup_logger()
    from storage import db
    db.init_db(db_path)
    try:
        from core.proxy import get_proxy_manager
        from core.conn import set_global_proxy_manager
        proxy_file = config.get("proxy_file", "proxies.txt")
        if os.path.exists(proxy_file):
            mgr = get_proxy_manager(proxy_file=proxy_file, auto_fetch=False)
            if mgr and mgr.proxies:
                set_global_proxy_manager(mgr)
                logger.info(f"[*] 已启用代理: {len(mgr.proxies)} 个")
    except Exception as e:
        logger.warning(f"[!] 代理初始化失败: {e}")
    logger.info(f"[*] Web 面板启动: http://{host}:{port}")
    if host in ("0.0.0.0", "::") and not state.get_web_token():
        logger.error("[!] 安全拦截：绑定 0.0.0.0 必须设置 web_token，拒绝启动")
        logger.error("[!] 请在 config.json 中设置 web_token，或绑定 127.0.0.1")
        import sys
        sys.exit(1)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run()
