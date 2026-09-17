# -*- coding: utf-8 -*-
"""Routes: config"""
from flask import request, jsonify, Response, send_from_directory
import os, sys, json, time, threading
from datetime import datetime
from collections import deque
import config, logger
from core.bot import DEFAULT_WARNING_MESSAGES
try:
    from web import state
except ImportError:
    import state  # type: ignore


def register(app):
    scan_state = state.scan_state
    scan_lock = state.scan_lock
    scan_stop_event = state.scan_stop_event
    observer_sessions = state.observer_sessions
    observer_lock = getattr(state, "observer_lock", state.scan_lock)
    health_monitor = state.health_monitor
    _ai_bots = state._ai_bots
    def _log(msg):
        state.log_scan(msg)
    def _get_web_token():
        return state.get_web_token()
    def _safe_db_path(path):
        return state.safe_db_path(path)
    def parse_ports_spec(ports_spec):
        return state.parse_ports_spec(ports_spec)


    @app.route('/api/config/default')
    def default_config():
        return jsonify({
            "workers": 32,
            "timeout": 4.0,
            "scan_threads": 200,
            "scan_timeout": 2.5,
            "rate": 0,
            "auth_check": True,
            "username": "SecurityBot",
            "messages": DEFAULT_WARNING_MESSAGES,
            "use_masscan": False,
            "portscan_only": False,
            "masscan_rate": 5000,
            "ports": [25565],
        })

    @app.route('/api/config/get')
    def config_get():
        """读取当前配置（敏感字段打码）"""
        cfg = config.get_all()
        # 敏感字段打码
        for k in ("ai_api_key", "web_token"):
            if cfg.get(k):
                v = str(cfg[k])
                cfg[k] = v[:4] + "****" + v[-2:] if len(v) > 8 else "****"
        return jsonify(cfg)

    @app.route('/api/config/save', methods=['POST'])
    def config_save():
        """保存配置到文件"""
        data = request.json or {}
        # 只允许保存白名单字段
        allowed = {"ai_api_key", "ai_base_url", "ai_model", "web_token", "web_host", "web_port",
                   "message_delay", "bot_timeout", "exclude_file", "db_path", "log_level",
                   "email_enabled", "email_smtp_host", "email_smtp_port", "email_smtp_ssl",
                   "email_username", "email_password", "email_from", "email_to"}
        to_save = {k: v for k, v in data.items() if k in allowed}
        # api_key如果是打码状态（含****），不覆盖原值
        if "ai_api_key" in to_save and "****" in str(to_save["ai_api_key"]):
            del to_save["ai_api_key"]
        if "web_token" in to_save and "****" in str(to_save["web_token"]):
            del to_save["web_token"]
        if "email_password" in to_save and "****" in str(to_save["email_password"]):
            del to_save["email_password"]
        ok = config.save_config(to_save)
        return jsonify({"success": ok, "saved": list(to_save.keys())})

    @app.route('/api/email/test', methods=['POST'])
    def email_test():
        """发送测试邮件"""
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
        body = f"""<html><body>
    <h2>MC扫描器邮件测试</h2>
    <p>如果你收到这封邮件，说明邮件配置正确！</p>
    <p>扫描完成后会自动发送结果摘要到这里。</p>
    <p style="color:#999;font-size:12px;">发送时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </body></html>"""
        ok, err = send_email(subject, body, html=True, cfg=cfg)
        return jsonify({"success": ok, "error": err})

