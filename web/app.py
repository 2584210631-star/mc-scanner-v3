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
    """API鉴权：静态资源放行；API 需要登录会话（X-API-Token 携带会话token）。
    首次登录未改密时，除改密/退出/状态接口外一律拒绝（强制先改密）。
    鉴权判断异常时拒绝访问（fail-closed）。"""
    path = request.path
    # 静态资源和页面放行
    if path in ("/", "/index.html") or path.startswith("/static/") or \
       path in ("/manifest.json", "/sw.js") or path.startswith("/ui-"):
        return None
    if not path.startswith("/api/"):
        return None
    # 登录接口本身无需鉴权
    if path == "/api/auth/login":
        return None
    try:
        from web import auth as web_auth
    except Exception:
        return jsonify({"error": "鉴权系统异常，拒绝访问"}), 500
    token = request.headers.get("X-API-Token", "")
    username = web_auth.verify_session(token)
    if not username:
        return jsonify({"error": "未登录或会话已过期", "code": "not_logged_in"}), 401
    # 首次登录必须改密：未改密时只放行改密/退出/状态接口
    if web_auth.load_account().get("must_change") and path not in (
            "/api/auth/change_password", "/api/auth/logout", "/api/auth/status"):
        return jsonify({"error": "首次登录必须先修改用户名和密码", "code": "must_change"}), 403
    return None


@app.before_request
def _audit_log():
    """写操作审计日志：记录所有POST/DELETE/PUT请求"""
    try:
        if request.method in ("POST", "DELETE", "PUT") and request.path.startswith("/api/"):
            ip = request.remote_addr or "unknown"
            # 提取目标信息（从请求体里取ip/port/target等关键字段）
            target = ""
            try:
                data = request.get_json(silent=True) or {}
                if data.get("ip") and data.get("port"):
                    target = f" {data['ip']}:{data['port']}"
                elif data.get("targets"):
                    target = f" targets={str(data['targets'])[:50]}"
                elif data.get("username"):
                    target = f" user={data['username']}"
            except Exception:
                pass
            logger.info(f"[审计] {ip} {request.method} {request.path}{target}")
    except Exception:
        pass
    return None


def _register_routes():
    modules = [
        "auth", "routes_core", "routes_scan", "routes_scan_extra", "routes_warn",
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
        logger.warning("[!] 已绑定 0.0.0.0（局域网可访问），所有 API 需登录（默认账号 admin/admin123，首次登录强制改密）")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run()
