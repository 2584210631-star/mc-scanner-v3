# -*- coding: utf-8 -*-
"""Routes: config"""
from flask import request, jsonify
from datetime import datetime
import config
from core.bot import DEFAULT_WARNING_MESSAGES
try:
    from web import state
except ImportError:
    import state  # type: ignore


def register(app):
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
        for k in ("ai_api_key", "web_token", "authme_password", "email_password"):
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

    @app.route('/api/config/read_only', methods=['POST'])
    def config_read_only():
        """切换只读模式：开启后禁止警告/进服/扫描等危险操作"""
        data = request.json or {}
        enabled = bool(data.get("enabled", False))
        state.set_read_only(enabled)
        # 同时持久化到config
        config.save_config({"read_only_mode": enabled})
        return jsonify({"success": True, "read_only": enabled})

    @app.route('/api/config/read_only', methods=['GET'])
    def config_read_only_status():
        return jsonify({"read_only": state.is_read_only()})

    @app.route('/api/config/mode', methods=['POST'])
    def config_set_mode():
        """切换应用模式：fun=搞怪模式（全功能），serious=正经模式（隐藏娱乐功能）"""
        data = request.json or {}
        mode = data.get("mode", "fun")
        if mode not in ("fun", "serious"):
            return jsonify({"error": "mode只能是fun或serious"}), 400
        config.save_config({"app_mode": mode})
        return jsonify({"success": True, "mode": mode})

    @app.route('/api/config/mode', methods=['GET'])
    def config_get_mode():
        return jsonify({"mode": config.get("app_mode", "fun")})

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

    # ===== 正版账号登录 =====
    _msa_state = {"step": "idle", "device_code": None, "interval": 5, "client_id": ""}

    @app.route('/api/msa/start', methods=['POST'])
    def msa_start():
        from core.microsoft_auth import start_device_code, CLIENT_ID
        data = request.get_json(silent=True) or {}
        cid = data.get("client_id", "") or CLIENT_ID
        try:
            r = start_device_code(cid)
            if "error" in r:
                return jsonify({"success": False, "error": r.get("error_description", str(r))})
            _msa_state["step"] = "waiting"
            _msa_state["device_code"] = r["device_code"]
            _msa_state["interval"] = r.get("interval", 5)
            _msa_state["client_id"] = cid
            return jsonify({"success": True, "user_code": r["user_code"],
                            "verification_uri": r["verification_uri"], "interval": r["interval"]})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)})

    @app.route('/api/msa/poll', methods=['GET', 'POST'])
    def msa_poll():
        from core.microsoft_auth import poll_token, full_login_flow
        # 支持POST传device_code，或GET用全局state
        device_code = None
        if request.method == 'POST':
            device_code = (request.get_json(silent=True) or {}).get("device_code", "") or request.form.get("device_code", "")
        if not device_code and _msa_state.get("step") == "waiting":
            device_code = _msa_state["device_code"]
        if not device_code:
            return jsonify({"success": False, "error": "未开始登录", "waiting": False})
        try:
            r = poll_token(device_code, _msa_state.get("client_id"))
            if "error" in r:
                err = r.get("error", "")
                if err == "expired_token" or err == "expired":
                    return jsonify({"success": False, "error": "expired", "waiting": False})
                # authorization_pending 或 slow_down 继续等
                return jsonify({"success": False, "waiting": True, "error": err})
            msa_token = r["access_token"]
            print(f"[MSA] 轮询成功，获取MSA token: {msa_token[:30]}...")
            result = full_login_flow(msa_token)
            cfg = config.get_all()
            cfg["msa_access_token"] = result["access_token"]
            cfg["msa_uuid"] = result["uuid"]
            cfg["msa_name"] = result["name"]
            config.save_config(cfg)
            _msa_state["step"] = "done"
            return jsonify({"success": True, "name": result["name"], "uuid": result["uuid"]})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e), "waiting": True})

    @app.route('/api/msa/status', methods=['GET'])
    def msa_status():
        name = config.get("msa_name", "")
        return jsonify({"logged_in": bool(name), "name": name})

    @app.route('/api/msa/auth_url', methods=['GET'])
    def msa_auth_url():
        """PCL2方式：获取授权码登录URL，WebView直接打开"""
        from core.microsoft_auth import get_auth_url
        cid = request.args.get("client_id", "")
        url = get_auth_url(cid or None)
        return jsonify({"url": url})

    @app.route('/api/msa/exchange', methods=['POST'])
    def msa_exchange():
        """WebView拦截到code后，用code换token"""
        from core.microsoft_auth import exchange_code, full_login_flow
        code = request.form.get("code", "") or (request.get_json(silent=True) or {}).get("code", "")
        if not code:
            return jsonify({"success": False, "error": "缺少code"})
        # URL解码
        import urllib.parse as _up
        code = _up.unquote(code)
        print(f"[MSA] 收到code: {code[:30]}... (长度{len(code)})")
        try:
            r = exchange_code(code)
            if "access_token" not in r:
                return jsonify({"success": False, "error": r.get("error_description", str(r))})
            msa_token = r["access_token"]
            result = full_login_flow(msa_token)
            cfg = config.get_all()
            cfg["msa_access_token"] = result["access_token"]
            cfg["msa_uuid"] = result["uuid"]
            cfg["msa_name"] = result["name"]
            config.save_config(cfg)
            return jsonify({"success": True, "name": result["name"]})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    @app.route('/api/msa/token', methods=['POST'])
    def msa_token():
        """直接用MSA access_token登录（隐式流程）"""
        from core.microsoft_auth import full_login_flow
        msa_token = request.form.get("access_token", "") or (request.get_json(silent=True) or {}).get("access_token", "")
        if not msa_token:
            return jsonify({"success": False, "error": "缺少access_token"})
        try:
            print(f"[MSA] 收到MSA token: {msa_token[:30]}...")
            result = full_login_flow(msa_token)
            cfg = config.get_all()
            cfg["msa_access_token"] = result["access_token"]
            cfg["msa_uuid"] = result["uuid"]
            cfg["msa_name"] = result["name"]
            config.save_config(cfg)
            return jsonify({"success": True, "name": result["name"]})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)})

