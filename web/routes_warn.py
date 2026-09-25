# -*- coding: utf-8 -*-
"""Routes: warn"""
from flask import request, jsonify
import time
import config
from core.bot import DEFAULT_WARNING_MESSAGES, join_and_warn
try:
    from web import state
except ImportError:
    import state  # type: ignore


def register(app):
    scan_state = state.scan_state
    scan_lock = state.scan_lock
    def _log(msg):
        state.log_scan(msg)
    def _get_web_token():
        return state.get_web_token()
    def _safe_db_path(path):
        return state.safe_db_path(path)
    def parse_ports_spec(ports_spec):
        return state.parse_ports_spec(ports_spec)


    @app.route('/api/warn/single', methods=['POST'])
    def warn_single():
        if state.is_read_only():
            return jsonify({"error": "只读模式下禁止警告操作"}), 403
        if not state.capability_enabled("login_interact"):
            return jsonify({"error": "进服交互能力未启用，请在config中设置 capabilities.login_interact=true"}), 403
        data = request.json or {}
        ip = data.get("ip")
        port = int(data.get("port") or 25565)
        username = data.get("username", "SecurityBot")
        messages = data.get("messages") or DEFAULT_WARNING_MESSAGES
        authme_password = data.get("authme_password")
        use_premium = bool(data.get("use_premium", False))
        premium_uuid = data.get("premium_uuid") or None
        if not ip:
            return jsonify({"error": "请指定 IP"}), 400
        # 从扫描结果中获取已知协议号，避免自动探测失败时遍历错误协议
        proto = None
        with scan_lock:
            for r in scan_state.get("results", []):
                if r.get("ip") == ip and int(r.get("port", 25565)) == port:
                    p = r.get("proto") or 0
                    if p and p > 0:
                        proto = p
                    break
        result = join_and_warn(ip, port, username, messages, timeout=15.0,
                                message_delay=0.8, protocol_version=proto,
                                authme_password=authme_password,
                                use_premium=use_premium, premium_uuid=premium_uuid)
        return jsonify({
            "success": result.success,
            "auth_mode": result.auth_mode,
            "messages_sent": result.messages_sent,
            "error": result.error,
            "version": result.version_name,
            "protocol_used": result.protocol_version,
        })

    @app.route('/api/warn/batch', methods=['POST'])
    def warn_batch():
        if state.is_read_only():
            return jsonify({"error": "只读模式下禁止警告操作"}), 403
        if not state.capability_enabled("login_interact"):
            return jsonify({"error": "进服交互能力未启用，请在config中设置 capabilities.login_interact=true"}), 403
        data = request.json or {}
        targets_raw = data.get("targets", [])
        username = data.get("username", "SecurityBot")
        messages = data.get("messages") or DEFAULT_WARNING_MESSAGES
        workers = int(data.get("workers", 5))
        authme_password = data.get("authme_password")
        message_delay = float(data.get("message_delay", 0.8))
        use_premium = bool(data.get("use_premium", False))
        premium_uuid = data.get("premium_uuid") or None

        # 解析目标列表，支持 [{"ip":...,"port":...,"proto":...}] 或 ["ip:port", ...]
        targets = []
        for t in targets_raw:
            if isinstance(t, dict):
                targets.append((t["ip"], int(t.get("port", 25565)), t.get("proto", 0)))
            elif isinstance(t, str) and ":" in t:
                ip, port = t.rsplit(":", 1)
                targets.append((ip, int(port), 0))
        if not targets:
            return jsonify({"error": "请先选择要警告的服务器"}), 400

        _log(f"批量警告开始，目标 {len(targets)} 个服务器")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(join_and_warn, ip, port, username, messages,
                                  timeout=15.0, message_delay=message_delay,
                                  protocol_version=proto or None, authme_password=authme_password,
                                  use_premium=use_premium, premium_uuid=premium_uuid): (ip, port)
                       for ip, port, proto in targets}
            for fut in as_completed(futures):
                try:
                    r = fut.result()
                    results.append({"ip": r.ip, "port": r.port, "success": r.success,
                                    "messages_sent": r.messages_sent, "error": r.error})
                except Exception as e:
                    ip, port = futures[fut]
                    results.append({"ip": ip, "port": port, "success": False, "error": str(e)})
        sent = sum(r["messages_sent"] for r in results)
        _log(f"批量警告完成，成功发送 {sent} 条消息")
        return jsonify({"total": len(results), "messages_sent": sent, "results": results})

    @app.route('/api/warn/multi', methods=['POST'])
    def warn_multi():
        """多机器人同时警告多个选中服务器"""
        if state.is_read_only():
            return jsonify({"error": "只读模式下禁止警告操作"}), 403
        if not state.capability_enabled("login_interact"):
            return jsonify({"error": "进服交互能力未启用，请在config中设置 capabilities.login_interact=true"}), 403
        data = request.json or {}
        targets_raw = data.get("targets", [])
        bot_count = int(data.get("bot_count", 5))
        name_prefix = data.get("name_prefix", "SecurityBot")
        messages = data.get("messages") or DEFAULT_WARNING_MESSAGES
        message_delay = float(data.get("message_delay", 0.5))
        authme_password = data.get("authme_password")
        workers = int(data.get("workers", 20))
        use_premium = bool(data.get("use_premium", False))
        premium_uuid = data.get("premium_uuid") or None

        # 解析目标列表
        targets = []
        for t in targets_raw:
            if isinstance(t, dict):
                targets.append((t["ip"], int(t.get("port", 25565)), t.get("proto", 0)))
            elif isinstance(t, str) and ":" in t:
                ip, port = t.rsplit(":", 1)
                targets.append((ip, int(port), 0))
        if not targets:
            return jsonify({"error": "请先选择要警告的服务器"}), 400
        max_bots = int(config.get("warn_bot_max", 20))
        if bot_count < 1 or bot_count > max_bots:
            return jsonify({"error": f"机器人数量需在 1-{max_bots} 之间"}), 400

        _log(f"多机器人警告开始：{len(targets)}台服务器 x {bot_count}个机器人")

        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = []

        def run_bot(ip, port, proto, idx):
            name = name_prefix  # 直接用输入的名字，不加_01后缀
            try:
                # 连接节流保护：1.12.2等旧版服务器默认 connection-throttle=4000ms
                # 同一IP 4秒内只能连一次，按编号错开连接时间
                if idx > 1:
                    time.sleep(4.5 * (idx - 1))
                r = join_and_warn(ip, port, name, messages, timeout=15.0,
                                  message_delay=message_delay,
                                  protocol_version=proto or None,
                                  authme_password=authme_password,
                                  use_premium=use_premium, premium_uuid=premium_uuid)
                return {"ip": ip, "port": port, "name": name, "success": r.success,
                        "messages_sent": r.messages_sent, "error": r.error}
            except Exception as e:
                return {"ip": ip, "port": port, "name": name, "success": False, "error": str(e)[:100]}

        with ThreadPoolExecutor(max_workers=min(workers, 50)) as ex:
            futures = []
            for ip, port, proto in targets:
                for i in range(bot_count):
                    futures.append(ex.submit(run_bot, ip, port, proto, i + 1))
            for fut in as_completed(futures):
                results.append(fut.result())

        success_count = sum(1 for r in results if r["success"])
        total_messages = sum(r["messages_sent"] for r in results)
        _log(f"多机器人警告完成：{success_count}/{len(results)}成功，共{total_messages}条消息")

        return jsonify({
            "total": len(results),
            "servers": len(targets),
            "bot_per_server": bot_count,
            "success": success_count,
            "messages_sent": total_messages,
            "results": results,
        })

    @app.route('/api/db/warn', methods=['POST'])
    def db_warn():
        """数据库一键警告：对选中服务器发送警告消息，支持AuthMe"""
        if state.is_read_only():
            return jsonify({"error": "只读模式下禁止警告操作"}), 403
        if not state.capability_enabled("login_interact"):
            return jsonify({"error": "进服交互能力未启用，请在config中设置 capabilities.login_interact=true"}), 403
        data = request.json or {}
        targets_raw = data.get("targets", [])
        username = data.get("username", "SecurityBot")
        messages = data.get("messages") or DEFAULT_WARNING_MESSAGES
        authme_password = data.get("authme_password")
        workers = int(data.get("workers", 5))
        message_delay = float(data.get("message_delay", 0.8))
        use_premium = bool(data.get("use_premium", False))
        premium_uuid = data.get("premium_uuid") or None

        targets = []
        for t in targets_raw:
            if isinstance(t, dict):
                targets.append((t["ip"], int(t.get("port", 25565))))
            elif isinstance(t, str) and ":" in t:
                ip, port = t.rsplit(":", 1)
                targets.append((ip, int(port)))
        if not targets:
            return jsonify({"error": "请先选择要警告的服务器"}), 400

        _log(f"数据库批量警告开始: {len(targets)} 个目标, authme={'是' if authme_password else '否'}")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(join_and_warn, ip, port, username, messages,
                                  timeout=15.0, message_delay=message_delay,
                                  protocol_version=None, authme_password=authme_password,
                                  use_premium=use_premium, premium_uuid=premium_uuid): (ip, port)
                       for ip, port in targets}
            for fut in as_completed(futures):
                try:
                    r = fut.result()
                    results.append({"ip": r.ip, "port": r.port, "success": r.success,
                                    "messages_sent": r.messages_sent, "error": r.error})
                except Exception as e:
                    ip, port = futures[fut]
                    results.append({"ip": ip, "port": port, "success": False, "error": str(e)})
        sent = sum(r["messages_sent"] for r in results)
        _log(f"数据库批量警告完成: 成功发送 {sent} 条消息")
        return jsonify({"total": len(results), "messages_sent": sent, "results": results})

