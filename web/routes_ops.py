# -*- coding: utf-8 -*-
"""Routes: ops"""
from flask import jsonify
import threading
try:
    from web import state
except ImportError:
    import state  # type: ignore


def register(app):
    health_monitor = state.health_monitor
    def _log(msg):
        state.log_scan(msg)
    def _safe_db_path(path):
        return state.safe_db_path(path)
    def parse_ports_spec(ports_spec):
        return state.parse_ports_spec(ports_spec)

    try:
        from web.services_health import _health_monitor_loop
    except ImportError:
        try:
            from services_health import _health_monitor_loop  # type: ignore
        except Exception:
            _health_monitor_loop = None


    @app.route('/api/health/status')
    def health_status():
        return jsonify({
            "running": health_monitor["running"],
            "interval": health_monitor["interval"],
            "last_check": health_monitor["last_check"],
            "monitored": len(health_monitor["status"]),
            "online_servers": sum(1 for s in health_monitor["status"].values() if s.get("online")),
            "events": health_monitor["events"][:30],
            "status": health_monitor["status"]
        })

    @app.route('/api/health/toggle', methods=['POST'])
    def health_toggle():
        if health_monitor["running"]:
            health_monitor["stop_event"].set()
            health_monitor["running"] = False
            return jsonify({"success": True, "running": False})
        else:
            health_monitor["stop_event"].clear()
            health_monitor["thread"] = threading.Thread(target=_health_monitor_loop, daemon=True)
            health_monitor["thread"].start()
            health_monitor["running"] = True
            return jsonify({"success": True, "running": True})

    @app.route('/api/health/run_once', methods=['POST'])
    def health_run_once():
        """立即手动跑一轮探测。监控正在运行时不重复触发，避免并发探测同一批服务器。"""
        if _health_monitor_loop is None:
            return jsonify({"success": False, "error": "监控模块未加载"}), 500
        if health_monitor.get("running"):
            return jsonify({"success": False, "error": "定时监控正在运行，本轮结束后会自动检查"}), 409
        threading.Thread(target=_health_monitor_loop, kwargs={"once": True}, daemon=True).start()
        return jsonify({"success": True})

