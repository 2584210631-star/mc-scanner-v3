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


# PWA 文件路由
@app.route('/manifest.json')
def _manifest():
    from flask import send_from_directory
    return send_from_directory(os.path.join(os.path.dirname(__file__), 'static'), 'manifest.json', mimetype='application/manifest+json')

@app.route('/sw.js')
def _sw():
    from flask import send_from_directory
    return send_from_directory(os.path.join(os.path.dirname(__file__), 'static'), 'sw.js', mimetype='application/javascript')




# API限流：按IP+模块，滑动窗口60秒
import time as _time
import threading as _threading
_rate_limit_store = {}  # (ip, module) -> [timestamps]
_rate_limit_lock = _threading.Lock()
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
        with _rate_limit_lock:
            # 清理过期时间戳，空列表的key也删掉防内存泄漏
            if key in _rate_limit_store:
                active = [t for t in _rate_limit_store[key] if now - t < _RATE_WINDOW]
                if active:
                    _rate_limit_store[key] = active
                else:
                    del _rate_limit_store[key]
            if key not in _rate_limit_store:
                _rate_limit_store[key] = []
            if len(_rate_limit_store[key]) >= limit:
                return jsonify({"error": f"请求过于频繁，{module}模块限{limit}次/分钟"}), 429
            _rate_limit_store[key].append(now)
    except Exception:
        pass
    return None


@app.before_request
def _check_auth():
    """API鉴权：静态资源放行，API需要X-API-Token"""
    try:
        path = request.path
        # 静态资源和页面放行
        if path in ("/", "/index.html") or path.startswith("/static/") or \
           path in ("/manifest.json", "/sw.js") or path.startswith("/ui-"):
            return None
        if not path.startswith("/api/"):
            return None
        token = config.get("web_token", "")
        if not token:
            return None  # 未配置token则不鉴权（本地127.0.0.1使用）
        client_token = request.headers.get("X-API-Token", "")
        if client_token != token:
            return jsonify({"error": "未授权访问，请配置正确的API Token"}), 401
    except Exception:
        pass
    return None


@app.before_request
def _serious_mode_check():
    """正经模式：危险操作需要confirm=true确认"""
    try:
        if config.get("app_mode", "fun") != "serious":
            return None
        path = request.path
        # 正经模式下需要确认的危险API
        dangerous = ("/api/warn/" in path and request.method == "POST") or \
                    ("/api/ai_multi/start" in path) or \
                    ("/api/ai_multi/stop" in path)
        if not dangerous:
            return None
        data = {}
        if request.method == "POST":
            try:
                data = request.get_json(silent=True) or {}
            except Exception:
                data = {}
        if not data.get("confirm"):
            return jsonify({"error": "正经模式下此操作需要确认，请在请求中加 confirm:true", "need_confirm": True}), 403
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
    if host in ("0.0.0.0", "::"):
        token = config.get("web_token", "")
        if not token:
            import secrets
            token = secrets.token_hex(16)
            config.set("web_token", token)
            config.save_config()
            logger.warning(f"[!] 0.0.0.0 绑定已自动生成 API Token: {token}")
            logger.warning("[!] 请在设置页填入此 Token，或使用 127.0.0.1 本地访问（无需鉴权）")
        else:
            logger.warning(f"[!] 0.0.0.0 绑定已启用 API Token 鉴权")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run()
