# -*- coding: utf-8 -*-
"""Routes: config"""
from flask import request, jsonify
from datetime import datetime
import config, logger
try:
    from web import state
except ImportError:
    import state  # type: ignore

def register(app):
    @app.route('/api/config/default')
    def default_config():
        try:
            from core.bot import DEFAULT_WARNING_MESSAGES
            messages = DEFAULT_WARNING_MESSAGES
        except Exception:
            messages = []
        return jsonify({
            "workers": 32, "timeout": 4.0, "scan_threads": 200, "scan_timeout": 2.5,
            "rate": 0, "auth_check": True, "username": "SecurityBot",
            "messages": messages, "use_masscan": False, "portscan_only": False,
            "masscan_rate": 5000, "ports": [25565],
        })

    @app.route('/api/config/get')
    def config_get():
        cfg = config.get_all() if hasattr(config, 'get_all') else {}
        for k in ("ai_api_key", "web_token"):
            if cfg.get(k):
                v = str(cfg[k])
                cfg[k] = v[:4] + "****" + v[-2:] if len(v) > 8 else "****"
        return jsonify(cfg)

    @app.route('/api/config/save', methods=['POST'])
    def config_save():
        data = request.json or {}
        allowed = {"ai_api_key", "ai_base_url", "ai_model", "web_token", "web_host", "web_port",
                   "message_delay", "bot_timeout", "exclude_file", "db_path", "log_level",
                   "email_enabled", "email_smtp_host", "email_smtp_port", "email_smtp_ssl",
                   "email_username", "email_password", "email_from", "email_to"}
        to_save = {k: v for k, v in data.items() if k in allowed}
        for k in ("ai_api_key", "web_token", "email_password"):
            if k in to_save and "****" in str(to_save[k]):
                del to_save[k]
        ok = config.save_config(to_save) if hasattr(config, 'save_config') else False
        return jsonify({"success": ok, "saved": list(to_save.keys())})

    @app.route('/api/email/test', methods=['POST'])
    def email_test():
        data = request.json or {}
        cfg = {
            "smtp_host": data.get("smtp_host") or config.get("email_smtp_host", ""),
            "smtp_port": data.get("smtp_port") or config.get("email_smtp_port", 465),
            "smtp_ssl": data.get("smtp_ssl", config.get("email_smtp_ssl", True)),
            "username": data.get("username") or config.get("email_username", ""),
            "password": data.get("password") or config.get("email_password", ""),
            "from": data.get("from_addr") or config.get("email_from", "") or config.get("email_username", ""),
            "to": data.get("to") or config.get("email_to", ""),
        }
        from core.notifier import send_email
        subject = "[MC扫描] 邮件测试"
        body = f"<html><body><h2>MC扫描器邮件测试</h2><p>配置正确即可收到。</p><p>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p></body></html>"
        ok, err = send_email(subject, body, html=True, cfg=cfg)
        return jsonify({"success": ok, "error": err})
