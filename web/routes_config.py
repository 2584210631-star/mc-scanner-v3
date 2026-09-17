# -*- coding: utf-8 -*-
"""Routes: config"""
from flask import request, jsonify
import config, logger
try:
    from web import state
except ImportError:
    import state  # type: ignore

def register(app):
    @app.route('/api/config/default')
    def default_config():
        return jsonify({
            "workers": 32, "timeout": 4.0, "scan_threads": 200, "scan_timeout": 2.5,
            "rate": 30, "auth_check": True, "use_masscan": False, "masscan_rate": 5000,
            "portscan_only": False, "continuous": False,
        })

    @app.route('/api/config/get')
    def config_get():
        cfg = config.load_config()
        # hide secrets partially
        safe = dict(cfg)
        for k in list(safe.keys()):
            if any(s in k.lower() for s in ('key', 'token', 'password', 'secret', 'webhook')):
                if safe[k]:
                    safe[k] = '***'
        return jsonify(safe)

    @app.route('/api/config/save', methods=['POST'])
    def config_save():
        data = request.json or {}
        cfg = config.load_config()
        for k, v in data.items():
            if v == '***':
                continue
            cfg[k] = v
        config.save_config(cfg)
        return jsonify({"success": True})

    @app.route('/api/email/test', methods=['POST'])
    def email_test():
        try:
            from core.notifier import send_test_email
            ok, err = send_test_email()
            return jsonify({"success": ok, "error": err})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)[:200]})
