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


# API限流：按IP+模块，滑动窗口60秒
import time as _time
_rate_limit_store = {}  # (ip, module) -> [timestamps]
_RATE_WINDOW = 60.0  # 秒

def _get_module(path):
    if path.startswith("/api/scan/") or path.startswith("/api/masscan/"):
        return "scan"
    if path.startswith("/api/warn/") or path == "/api/db/warn":
        return "warn"
    if path.startswith("/api/ai_bot/") or path.startswith("/api/ai_multi/") or path.startswith("/api/assistant/"):
        return "ai"
    return None

@app.before_request
def _rate_limit():
    try:
        limit = int(config.get("api_rate_limit", 0))
        if limit <= 0:
            return None
        module = _get_module(request.path)
        if not module:
            return None
        ip = request.remote_addr or "unknown"
        key = (ip, module)
        now = _time.time()
        # 清理过期时间戳
        if key in _rate_limit_store:
            _rate_limit_store[key] = [t for t in _rate_limit_store[key] if now - t < _RATE_WINDOW]
        else:
            _rate_limit_store[key] = []
        if len(_rate_limit_store[key]) >= limit:
            return jsonify({"error": f"请求过于频繁，{module}模块限{limit}次/分钟"}), 429
        _rate_limit_store[key].append(now)
    except Exception:
        pass
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
    # 定期清理超旧离线记录
    try:
        retention = int(config.get("db_retention_days", 0))
        if retention > 0:
            deleted = db.clean_old_records(db_path, retention_days=retention, only_offline=True)
            if deleted > 0:
                logger.info(f"[*] 清理超旧离线记录: {deleted} 条（保留{retention}天）")
    except Exception as e:
        logger.warning(f"[!] 旧记录清理失败: {e}")
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
