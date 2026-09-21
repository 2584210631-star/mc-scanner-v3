# -*- coding: utf-8 -*-
"""Routes: observer"""
from flask import request, jsonify, Response
import os
import json
import time
import threading
from datetime import datetime
try:
    from web import state
except ImportError:
    import state  # type: ignore
try:
    from web.observer_session import ObserverSession
except ImportError:
    from observer_session import ObserverSession  # type: ignore


def _html_escape(s):
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def register(app):
    observer_sessions = state.observer_sessions
    observer_lock = state.observer_lock
    def _log(msg):
        state.log_scan(msg)
    def _get_web_token():
        return state.get_web_token()
    def _safe_db_path(path):
        return state.safe_db_path(path)
    def parse_ports_spec(ports_spec):
        return state.parse_ports_spec(ports_spec)


    @app.route('/api/observer/start', methods=['POST'])
    def observer_start():
        if state.is_read_only():
            return jsonify({"error": "只读模式下禁止观察者进服"}), 403
        data = request.json or {}
        host = data.get("host")
        port = int(data.get("port") or 25565)
        username = data.get("username", "Observer")
        authme = data.get("authme_password") or None
        timeout = float(data.get("timeout", 20.0))
        duration = max(0, float(data.get("duration", 0) or 0))
        if not host:
            return jsonify({"error": "host 不能为空"}), 400
        if not username:
            return jsonify({"error": "用户名不能为空"}), 400
        # 观察者不传protocol_version，让MCBot自动SLP探测后直接连（和昨天版本一致）
        session = ObserverSession(host, port, username, authme_password=authme,
                                  timeout=timeout, duration=duration)
        session.session_id = f"{int(time.time() * 1000)}-{os.getpid()}-{len(observer_sessions) + 1}"
        session.thread = threading.Thread(target=session.run, daemon=True)
        with observer_lock:
            observer_sessions[session.session_id] = session
        session.thread.start()
        _log(f"观察者启动: {username} -> {host}:{port} [{session.session_id[-6:]}]")
        return jsonify({"success": True, "session_id": session.session_id, "status": session.status})

    @app.route('/api/observer/list')
    def observer_list():
        with observer_lock:
            sessions = [s.brief() for s in observer_sessions.values()]
        return jsonify({"total": len(sessions), "sessions": sessions})

    @app.route('/api/observer/history')
    def observer_history():
        """列出所有已保存的历史会话（断开/被ban后仍可导出）"""
        logs = []
        log_dir = 'observer_logs'
        if os.path.exists(log_dir):
            for fname in sorted(os.listdir(log_dir), reverse=True):
                if fname.endswith('.json'):
                    try:
                        with open(os.path.join(log_dir, fname), 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        logs.append({
                            'session_id': data.get('session_id', fname.replace('.json','')),
                            'host': data.get('host', '?'),
                            'port': data.get('port', 0),
                            'username': data.get('username', '?'),
                            'status': data.get('status', 'disconnected'),
                            'msg_count': len(data.get('chat_log', [])),
                            'saved_at': data.get('saved_at', ''),
                        })
                    except Exception:
                        pass
        return jsonify({"total": len(logs), "sessions": logs[:50]})

    @app.route('/api/observer/status')
    def observer_status():
        sid = request.args.get("session_id", "")
        since = request.args.get("since", type=int)
        with observer_lock:
            session = observer_sessions.get(sid)
        if not session:
            return jsonify({"error": "会话不存在或已过期"}), 404
        return jsonify(session.full(since=since))

    @app.route('/api/observer/stop', methods=['POST'])
    def observer_stop():
        data = request.json or {}
        sid = data.get("session_id", "")
        with observer_lock:
            session = observer_sessions.get(sid)
        if not session:
            return jsonify({"error": "会话不存在或已过期"}), 404
        session.stop()
        _log(f"观察者停止: {session.username} -> {session.host}:{session.port}")
        return jsonify({"success": True, "session_id": sid, "status": session.status})

    @app.route('/api/observer/stop_all', methods=['POST'])
    def observer_stop_all():
        with observer_lock:
            sessions = list(observer_sessions.values())
        stopped = 0
        for s in sessions:
            try:
                s.stop()
                stopped += 1
            except Exception:
                pass
        _log(f"一键停止全部观察者: {stopped}个")
        return jsonify({"success": True, "stopped": stopped})

    @app.route('/api/observer/send', methods=['POST'])
    def observer_send():
        data = request.json or {}
        sid = data.get("session_id", "")
        msg_type = data.get("type", "chat")  # chat / command
        message = data.get("message", "")
        with observer_lock:
            session = observer_sessions.get(sid)
        if not session:
            return jsonify({"error": "会话不存在或已过期"}), 404
        if session.status != "connected" or not session.bot:
            return jsonify({"error": "观察者未连接"}), 400
        if not message:
            return jsonify({"error": "消息不能为空"}), 400
        try:
            if msg_type == "command":
                session.bot.send_command(message)
            else:
                session.bot.send_chat(message)
            print(f"[观察者发送] {session.username} -> {session.host}:{session.port} [{msg_type}] {message[:50]}")
            return jsonify({"success": True, "type": msg_type, "message": message})
        except Exception as e:
            print(f"[观察者发送失败] {session.username} -> {session.host}:{session.port} [{msg_type}] {message[:50]} 错误: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)[:200]})

    @app.route('/api/observer/export')
    def observer_export():
        """导出观察者聊天记录，支持 txt 和 html 格式。会话进行中也能下载（读实时jsonl）"""
        sid = request.args.get("session_id", "")
        fmt = request.args.get("format", "txt").lower()
        safe_id = sid.replace('/', '_').replace('\\', '_')
        messages = []
        host = "unknown"
        port = 0
        username = "unknown"

        # 1. 优先从内存读（会话进行中）
        with observer_lock:
            session = observer_sessions.get(sid)
        if session:
            messages = list(session.chat_log)
            host = session.host
            port = session.port
            username = session.username
        else:
            # 2. 从实时jsonl读（被ban/踢但文件还在）
            jsonl_file = f'observer_logs/{safe_id}.jsonl'
            json_file = f'observer_logs/{safe_id}.json'
            if os.path.exists(jsonl_file):
                try:
                    with open(jsonl_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            rec = json.loads(line)
                            messages.append((rec.get("seq", 0), rec.get("time", ""),
                                             rec.get("sender", ""), rec.get("text", "")))
                            if not host or host == "unknown":
                                host = rec.get("host", "unknown")
                                port = rec.get("port", 0)
                                username = rec.get("observer", "unknown")
                    _log(f"从实时jsonl导出 {len(messages)} 条")
                except Exception as e:
                    return jsonify({"error": f"读取实时记录失败: {e}"}), 500
            elif os.path.exists(json_file):
                # 3. 从结束快照读
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    messages = data.get('chat_log', [])
                    host = data.get('host', 'unknown')
                    port = data.get('port', 0)
                    username = data.get('username', 'unknown')
                except Exception as e:
                    return jsonify({"error": f"读取记录失败: {e}"}), 500
            else:
                return jsonify({"error": "会话不存在或已过期"}), 404
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if fmt == "html":
            rows = ""
            for seq, ts, sender, text in messages:
                color = "#e94560" if sender == username else "#00d992"
                rows += f'<div class="msg"><span class="time">{_html_escape(ts)}</span><span class="sender" style="color:{color}">{_html_escape(sender)}</span><span class="text">{_html_escape(text)}</span></div>\n'
            html = f"""<!DOCTYPE html>
    <html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>观察者记录 - {_html_escape(str(host))}:{_html_escape(str(port))}</title>
    <style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0a0a0a;color:#e0e0e0;font-family:Consolas,Monaco,monospace;padding:20px}}
    .container{{max-width:900px;margin:0 auto}}
    .header{{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #0f3460;border-radius:12px;padding:24px;margin-bottom:20px}}
    .header h1{{color:#00d992;font-size:22px;margin-bottom:10px}}
    .header .info{{color:#888;font-size:13px}}.header .info span{{color:#e94560}}
    .chat{{background:#111;border:1px solid #222;border-radius:12px;overflow:hidden}}
    .msg{{padding:8px 16px;border-bottom:1px solid #1a1a1a;display:flex;gap:12px;font-size:13px}}
    .msg:hover{{background:#161616}}
    .msg .time{{color:#555;min-width:60px}}.msg .sender{{font-weight:bold;min-width:100px}}.msg .text{{color:#ccc;flex:1;word-break:break-all}}
    .footer{{text-align:center;color:#444;font-size:12px;margin-top:16px}}</style>
    </head><body><div class="container">
    <div class="header"><h1>观察者聊天记录</h1>
    <div class="info">服务器: <span>{_html_escape(str(host))}:{_html_escape(str(port))}</span> | 观察者: <span>{_html_escape(username)}</span> | 导出时间: <span>{now}</span> | 消息数: <span>{len(messages)}</span></div>
    </div><div class="chat">{rows}</div>
    <div class="footer">Generated by mc-scanner-v3 Observer</div>
    </div></body></html>"""
            return Response(html, mimetype="text/html; charset=utf-8",
                            headers={"Content-Disposition": f"attachment; filename=observer_{host}_{port}_{int(time.time())}.html"})
        else:
            lines = ["观察者聊天记录", f"服务器: {host}:{port}", f"观察者: {username}",
                     f"导出时间: {now}", f"消息数: {len(messages)}", "=" * 50, ""]
            for seq, ts, sender, text in messages:
                lines.append(f"[{ts}] {sender}: {text}")
            txt = "\n".join(lines)
            return Response(txt, mimetype="text/plain; charset=utf-8",
                            headers={"Content-Disposition": f"attachment; filename=observer_{host}_{port}_{int(time.time())}.txt"})

