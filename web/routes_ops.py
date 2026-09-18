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
    def _get_web_token():
        return state.get_web_token()
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

