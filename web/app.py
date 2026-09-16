# -*- coding: utf-8 -*-
"""
Web 控制面板（Flask 实现）。
功能：实时扫描、结果筛选/搜索、版本分布图、导出 JSON/CSV、单独/批量警告、
数据库管理、masscan 高速扫描、只扫端口、导入 masscan 结果、给服务器发命令、生成协议表。
"""
import json
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, Response

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import logger

# 关闭 Flask/Werkzeug 默认的 HTTP 请求访问日志（避免轮询刷屏）
import logging
logging.getLogger('werkzeug').setLevel(logging.WARNING)

from storage import db
from storage import favorites
from scanner.engine import ScanEngine
from scanner.random_scan import random_scan, parse_port_ranges
from scanner.targets import parse_targets, count_targets
from scanner.exclude import Excluder
from scanner.masscan import has_masscan, run_masscan, parse_masscan_json, get_masscan_version
from scanner.portscan import scan_ports, get_open_ports
from core.bot import join_and_warn, DEFAULT_WARNING_MESSAGES, MCBot
from core.protocol import get_version_name


def parse_ports_spec(ports_spec):
    """解析端口规格，支持单个端口、逗号分隔、范围(25565-25575)、混合。空值默认[25565]"""
    if ports_spec is None or (isinstance(ports_spec, str) and not ports_spec.strip()):
        return [25565]
    if isinstance(ports_spec, list):
        result = []
        for p in ports_spec:
            result.extend(parse_ports_spec(p))
        return sorted(set(result))
    if not isinstance(ports_spec, str):
        return [int(ports_spec)]
    result = []
    for part in ports_spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                start = int(start.strip())
                end = int(end.strip())
                if start > end:
                    start, end = end, start
                result.extend(range(start, end + 1))
            except ValueError:
                continue
        else:
            try:
                result.append(int(part))
            except ValueError:
                continue
    return sorted(set(result))

app = Flask(__name__)
# Flask 2.x 用 config，Flask 3.x 用 app.json.ensure_ascii
try:
    app.json.ensure_ascii = False
except AttributeError:
    app.config['JSON_AS_ASCII'] = False


def _get_web_token():
    """获取Web访问token，空字符串表示不启用认证。"""
    return config.get("web_token", "") or ""


def _safe_db_path(path: str) -> str:
    """校验数据库路径，防止路径遍历攻击。只允许当前目录下的 .db 文件。"""
    if not path:
        return "mcscanner.db"
    # 禁止路径遍历
    if ".." in path or path.startswith("/") or (len(path) >= 2 and path[1] == ":"):
        return "mcscanner.db"
    # 只允许 .db 后缀
    if not path.endswith(".db"):
        return "mcscanner.db"
    return path


@app.before_request
def _check_token():
    """API请求token认证（首页和静态文件除外）。"""
    token = _get_web_token()
    if not token:
        return None
    if request.path == '/' or request.path.startswith('/static/'):
        return None
    if request.path.startswith('/api/'):
        client_token = request.headers.get('X-API-Token', '') or request.args.get('token', '')
        if client_token != token:
            return jsonify({"error": "未授权访问，请配置正确的API Token"}), 401
    return None


scan_stop_event = threading.Event()

scan_state = {
    "running": False,
    "progress": 0,
    "total": 0,
    "scanned": 0,
    "open_count": 0,
    "results": [],
    "logs": [],
    "start_time": None,
    "task_id": None,
    "history": [],
}
scan_lock = threading.Lock()
task_counter = 0


def _log(msg: str):
    logger.info(msg)
    with scan_lock:
        entry = {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg}
        scan_state["logs"].append(entry)
        if len(scan_state["logs"]) > 500:
            scan_state["logs"] = scan_state["logs"][-500:]


def _scan_worker(targets_list, config):
    global task_counter
    try:
        task_counter += 1
        scan_stop_event.clear()
        with scan_lock:
            scan_state["task_id"] = task_counter
            scan_state["running"] = True
            scan_state["results"] = []
            scan_state["logs"] = []
            scan_state["progress"] = 0
            scan_state["scanned"] = 0
            scan_state["open_count"] = 0
            scan_state["start_time"] = time.time()
        _log(f"任务 #{task_counter} 开始，目标数: {len(targets_list)}")

        # 进度回调：实时更新扫描状态
        total_targets = len(targets_list)
        def _on_progress(done, total, open_count):
            with scan_lock:
                scan_state["scanned"] = done
                scan_state["total"] = total
                scan_state["progress"] = int(done * 100 / total) if total else 0
                scan_state["open_count"] = open_count

        # 连续扫描模式：大网段拆成 /24 逐个扫描
        if config.get("continuous"):
            import ipaddress
            subnets = []
            for t in targets_list:
                # targets_list 是 (ip, port) tuple 列表，连续扫描只需要 IP 部分
                if isinstance(t, (tuple, list)):
                    t = str(t[0]).strip()
                else:
                    t = str(t).strip()
                if not t:
                    continue
                try:
                    net = ipaddress.ip_network(t, strict=False)
                    if net.prefixlen < 24:
                        for subnet in net.subnets(new_prefix=24):
                            subnets.append(str(subnet))
                    else:
                        subnets.append(t)
                except:
                    subnets.append(t)
            _log(f"连续扫描模式: 拆分为 {len(subnets)} 个 /24 网段")
            from scanner.async_engine import AsyncScanEngine
            all_results = []
            for i, subnet in enumerate(subnets):
                _log(f"连续扫描 [{i+1}/{len(subnets)}]: {subnet}")
                try:
                    sub_targets = list(parse_targets([subnet], config.get("ports", [25565])))
                    if not sub_targets:
                        continue
                    engine = AsyncScanEngine(stop_event=scan_stop_event, 
                        db_path=config.get("db_path", "mcscanner.db"),
                        concurrency=config.get("scan_threads", 200),
                        slp_concurrency=min(400, config.get("workers", 32) * 10),
                        timeout=config.get("timeout", 4.0),
                        auth_check=config.get("auth_check", True),
                        rate_limit=config.get("rate", 0),
                    )
                    sub_results = engine.scan_with_portscan(
                        iter(sub_targets),
                        scan_concurrency=config.get("scan_threads", 200),
                        scan_timeout=config.get("scan_timeout", 2.5),
                        progress_callback=_on_progress,
                    )
                    # 只保留up结果，避免大范围连续扫描时offline结果占满内存
                    up_results = [r for r in sub_results if r.get("state") == "up"]
                    all_results.extend(up_results)
                    with scan_lock:
                        scan_state["results"] = all_results
                        scan_state["progress"] = int((i + 1) * 100 / len(subnets)) if subnets else 100
                    _log(f"  网段 {subnet} 完成，累计 {len(all_results)} 个在线服务器")
                except Exception as e:
                    _log(f"  网段 {subnet} 出错: {e}")
            with scan_lock:
                scan_state["results"] = all_results
                scan_state["progress"] = len(all_results)
                scan_state["total"] = len(all_results)
            _log(f"连续扫描完成，共 {len(all_results)} 个服务器")
            # 邮件通知
            try:
                from core.notifier import notify_scan_complete
                duration = time.time() - scan_state.get("start_time", time.time())
                ok, err = notify_scan_complete(all_results, len(targets_list), duration, task_counter)
                if ok:
                    _log("扫描完成邮件已发送")
                elif err and "未启用" not in err:
                    _log(f"邮件通知失败: {err}")
            except Exception as e:
                _log(f"邮件通知异常: {e}")
            history_entry = {
                "id": task_counter,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "targets": len(targets_list),
                "found": len(all_results),
                "mode": "continuous",
                "config": {k: v for k, v in config.items() if k != "db_path"},
            }
            with scan_lock:
                scan_state["history"].insert(0, history_entry)
                if len(scan_state["history"]) > 20:
                    scan_state["history"] = scan_state["history"][:20]
            return

        use_masscan = config.get("use_masscan", False)
        portscan_only = config.get("portscan_only", False)
        results = []

        if use_masscan:
            if not has_masscan():
                _log("masscan 未找到，回退到 Python 扫描")
                use_masscan = False
            else:
                _log(f"使用 masscan 高速扫描，速率: {config.get('masscan_rate', 5000)}/s")
                # targets_list 是 (ip, port) tuple，masscan 只需要 IP（去重）
                unique_ips = list(dict.fromkeys(t[0] if isinstance(t, (tuple, list)) else str(t) for t in targets_list))
                targets_str = ",".join(unique_ips)
                ports_str = ",".join(str(p) for p in config.get("ports", [25565]))
                try:
                    ndjson_path = run_masscan(
                        targets=targets_str,
                        ports=ports_str,
                        rate=config.get("masscan_rate", 5000),
                        exclude_file=config.get("exclude_file", "exclude.conf"),
                    )
                    _log(f"masscan 扫描完成: {ndjson_path}")
                    if portscan_only:
                        raw = parse_masscan_json(ndjson_path)
                        results = [{"ip": ip, "port": port, "auth": "unknown",
                                    "version": None, "motd": None,
                                    "players_online": 0, "players_max": 0,
                                    "ping_ms": None, "proto": None}
                                   for ip, port, _ in raw]
                    else:
                        engine = ScanEngine(stop_event=scan_stop_event, 
                            db_path=config.get("db_path", "mcscanner.db"),
                            workers=config.get("workers", 32),
                            timeout=config.get("timeout", 4.0),
                            auth_check=config.get("auth_check", True),
                            rate_limit=config.get("rate", 0),
                        )
                        results = engine.import_masscan(ndjson_path, then_auth=config.get("auth_check", True))
                        _log(f"认证检测完成，共 {len(results)} 个服务器")
                except Exception as e:
                    _log(f"masscan 出错: {e}，回退 Python 扫描")
                    use_masscan = False

        if not use_masscan:
            if portscan_only:
                _log("只扫端口模式（不做 SLP 探测）")
                raw_results = scan_ports(
                    targets_list,
                    max_workers=config.get("scan_threads", 200),
                    timeout=config.get("scan_timeout", 2.5),
                    progress_callback=_on_progress,
                )
                open_ports = get_open_ports(raw_results)
                results = [{"ip": ip, "port": port, "auth": "unknown",
                            "version": None, "motd": None,
                            "players_online": 0, "players_max": 0,
                            "ping_ms": None, "proto": None}
                           for ip, port in open_ports]
                _log(f"端口扫描完成，开放: {len(results)} 个")
            else:
                if config.get("async_mode"):
                    from scanner.async_engine import AsyncScanEngine
                    from scanner.async_portscan import has_uvloop
                    from scanner.async_probe import has_simdjson
                    _log(f"异步流水线扫描（uvloop: {'启用' if has_uvloop() else '未安装'}, "
                         f"simdjson: {'启用' if has_simdjson() else '未安装'}）")
                    async_engine = AsyncScanEngine(
                        db_path=config.get("db_path", "mcscanner.db"),
                        concurrency=config.get("scan_threads", 1000),
                        slp_concurrency=config.get("workers", 200),
                        timeout=config.get("timeout", 4.0),
                        auth_check=config.get("auth_check", True),
                        rate_limit=config.get("rate", 0),
                        stop_event=scan_stop_event,
                    )
                    results = async_engine.scan_with_portscan(iter(targets_list))
                else:
                    engine = ScanEngine(stop_event=scan_stop_event, 
                        db_path=config.get("db_path", "mcscanner.db"),
                        workers=config.get("workers", 32),
                        timeout=config.get("timeout", 4.0),
                        auth_check=config.get("auth_check", True),
                        rate_limit=config.get("rate", 0),
                    )
                    results = engine.scan_with_portscan(
                        iter(targets_list),
                        scan_threads=config.get("scan_threads", 200),
                        scan_timeout=config.get("scan_timeout", 2.5),
                        progress_callback=_on_progress,
                    )

        with scan_lock:
            scan_state["results"] = results
            scan_state["progress"] = 100
            scan_state["total"] = len(results)
        _log(f"扫描完成，共发现 {len(results)} 个服务器")

        # 邮件通知
        try:
            from core.notifier import notify_scan_complete
            duration = time.time() - scan_state.get("start_time", time.time())
            ok, err = notify_scan_complete(results, len(targets_list), duration, task_counter)
            if ok:
                _log("扫描完成邮件已发送")
            elif err and "未启用" not in err:
                _log(f"邮件通知失败: {err}")
        except Exception as e:
            _log(f"邮件通知异常: {e}")

        with scan_lock:
            history_entry = {
                "id": task_counter,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "targets": len(targets_list),
                "found": len(results),
                "mode": "masscan" if use_masscan else ("portscan" if portscan_only else "full"),
                "config": {k: v for k, v in config.items() if k != "db_path"},
            }
            scan_state["history"].insert(0, history_entry)
            if len(scan_state["history"]) > 20:
                scan_state["history"] = scan_state["history"][:20]
    except Exception as e:
        import traceback
        _log(f"扫描出错: {e}")
        _log(f"错误详情: {traceback.format_exc()}")
        with scan_lock:
            scan_state["error"] = str(e)
            scan_state["traceback"] = traceback.format_exc()
    finally:
        scan_stop_event.clear()
        with scan_lock:
            scan_state["running"] = False


# ===== 观察者（Observer）会话管理 =====
# 登录指定服务器并保持连接，实时记录聊天消息与玩家进出，支持观察中发消息/命令。
class ObserverSession:
    """单个服务器观察者会话"""
    def __init__(self, host, port, username, authme_password=None, timeout=20.0, duration=0, protocol_version=None):
        self.session_id = ""
        self.duration = duration  # 观察时长（秒），0=一直观察
        self.host = host
        self.port = port
        self.username = username
        self.authme_password = authme_password
        self.timeout = timeout
        self.protocol_version = protocol_version
        self.bot = None
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.status = "connecting"  # connecting / connected / disconnected / stopped / error
        self.error = ""
        self.auth_mode = "unknown"
        self.version_name = ""
        self.start_time = time.time()
        self.connect_time = None
        self.disconnect_time = None
        self.chat_log = deque(maxlen=1000)   # (seq, time_str, text)
        self.events = deque(maxlen=2000)     # (seq, time_str, type, text)  type: chat/join/leave
        self._seq = 0

    def _next_seq(self):
        self._seq += 1
        return self._seq

    @staticmethod
    def _ts():
        return datetime.now().strftime("%H:%M:%S")

    def _on_chat(self, text, sender="未知"):
        try:
            with self.lock:
                self.events.append((self._next_seq(), self._ts(), "chat", sender, text))
                self.chat_log.append((self._seq, self._ts(), sender, text))
        except Exception:
            pass

    def _on_player(self, name, action):
        try:
            with self.lock:
                self.events.append((self._next_seq(), self._ts(), action, name))
        except Exception:
            pass

    def run(self):
        try:
            self.bot = MCBot(host=self.host, port=self.port,
                             username=self.username, timeout=self.timeout,
                             protocol_version=self.protocol_version)
            self.bot.chat_callback = self._on_chat
            self.bot.player_callback = self._on_player
            self.bot.connect()
            with self.lock:
                self.status = "connected"
                self.auth_mode = self.bot.auth_mode
                self.version_name = get_version_name(self.bot.protocol_version)
                self.protocol_version = self.bot.protocol_version
                self.connect_time = time.time()
            if self.authme_password:
                try:
                    self.bot.authme_login(self.authme_password, register=False)
                except Exception:
                    pass
            # 保持连接：直到手动停止、观察时长到期或服务器断开
            while not self.stop_event.is_set():
                if not getattr(self.bot, "connected", True):
                    with self.lock:
                        self.status = "disconnected"
                        self.disconnect_time = time.time()
                    return
                if self.duration > 0 and (time.time() - self.connect_time) >= self.duration:
                    with self.lock:
                        self.status = "stopped"
                        self.disconnect_time = time.time()
                    return
                time.sleep(0.5)
            with self.lock:
                self.status = "stopped"
                self.disconnect_time = time.time()
        except Exception as e:
            with self.lock:
                self.status = "error"
                self.error = str(e)[:300]
            print(f"[观察者错误] {self.username}@{self.host}:{self.port} - {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.bot:
                try:
                    self.bot.close()
                except Exception:
                    pass
            # 会话结束前保存聊天记录到文件，被ban/踢后仍可导出
            try:
                os.makedirs('observer_logs', exist_ok=True)
                safe_id = self.session_id.replace('/', '_').replace('\\', '_')
                with open(f'observer_logs/{safe_id}.json', 'w', encoding='utf-8') as f:
                    json.dump({
                        'session_id': self.session_id,
                        'host': self.host, 'port': self.port,
                        'username': self.username,
                        'status': self.status,
                        'chat_log': list(self.chat_log),
                        'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }, f, ensure_ascii=False)
            except Exception:
                pass
            # 会话结束后从全局字典移除，防止内存泄漏
            try:
                with observer_lock:
                    observer_sessions.pop(self.session_id, None)
            except Exception:
                pass

    def stop(self):
        self.stop_event.set()

    def _players(self):
        if not self.bot:
            return []
        try:
            return sorted(set(v for v in self.bot.player_list.values() if v))
        except Exception:
            return []

    def brief(self):
        with self.lock:
            return {
                "session_id": self.session_id,
                "host": self.host,
                "port": self.port,
                "username": self.username,
                "status": self.status,
                "error": self.error,
                "auth_mode": self.auth_mode,
                "version_name": self.version_name,
                "uptime": time.time() - self.start_time,
                "players_online": len(self._players()),
                "chat_count": len(self.chat_log),
            }

    def full(self, since=None):
        with self.lock:
            players = self._players()
            all_events = list(self.events)
            last_seq = self._seq
        if since is not None:
            all_events = [e for e in all_events if e[0] > since]
        # events: chat=(seq,time,type,sender,text)  join/leave=(seq,time,type,name)
        events_out = []
        for e in all_events[-100:]:
            if e[2] == "chat":
                events_out.append({"seq": e[0], "time": e[1], "type": e[2], "sender": e[3], "text": e[4]})
            else:
                events_out.append({"seq": e[0], "time": e[1], "type": e[2], "name": e[3]})
        return {
            "session_id": self.session_id,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "status": self.status,
            "error": self.error,
            "auth_mode": self.auth_mode,
            "version_name": self.version_name,
            "protocol_version": self.protocol_version,
            "start_time": self.start_time,
            "connect_time": self.connect_time,
            "uptime": time.time() - self.start_time,
            "players_online": len(players),
            "players": players,
            "events": events_out,
            "last_seq": last_seq,
            "chat": list(self.chat_log),
        }


observer_sessions = {}
observer_lock = threading.Lock()


@app.route('/api/observer/start', methods=['POST'])
def observer_start():
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
    """导出观察者聊天记录，支持 txt 和 html 格式"""
    sid = request.args.get("session_id", "")
    fmt = request.args.get("format", "txt").lower()
    with observer_lock:
        session = observer_sessions.get(sid)
    if session:
        messages = list(session.chat_log)
        host = session.host
        port = session.port
        username = session.username
    else:
        # 会话已结束（被ban/踢），从保存的文件读取
        safe_id = sid.replace('/', '_').replace('\\', '_')
        log_file = f'observer_logs/{safe_id}.json'
        if not os.path.exists(log_file):
            return jsonify({"error": "会话不存在或已过期"}), 404
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            messages = data.get('chat_log', [])
            host = data.get('host', 'unknown')
            port = data.get('port', 0)
            username = data.get('username', 'unknown')
        except Exception as e:
            return jsonify({"error": f"读取记录失败: {e}"}), 500
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if fmt == "html":
        rows = ""
        for seq, ts, sender, text in messages:
            color = "#e94560" if sender == username else "#00d992"
            rows += f'<div class="msg"><span class="time">{ts}</span><span class="sender" style="color:{color}">{sender}</span><span class="text">{text}</span></div>\n'
        html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>观察者记录 - {host}:{port}</title>
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
<div class="info">服务器: <span>{host}:{port}</span> | 观察者: <span>{username}</span> | 导出时间: <span>{now}</span> | 消息数: <span>{len(messages)}</span></div>
</div><div class="chat">{rows}</div>
<div class="footer">Generated by mc-scanner-v3 Observer</div>
</div></body></html>"""
        return Response(html, mimetype="text/html; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=observer_{host}_{port}_{int(time.time())}.html"})
    else:
        lines = [f"观察者聊天记录", f"服务器: {host}:{port}", f"观察者: {username}",
                 f"导出时间: {now}", f"消息数: {len(messages)}", "=" * 50, ""]
        for seq, ts, sender, text in messages:
            lines.append(f"[{ts}] {sender}: {text}")
        txt = "\n".join(lines)
        return Response(txt, mimetype="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=observer_{host}_{port}_{int(time.time())}.txt"})


@app.route('/')
def index():
    return send_from_directory(os.path.dirname(__file__), 'index.html')


@app.route('/api/scan/start', methods=['POST'])
def start_scan():
    data = request.json or {}
    targets_str = data.get("targets", "")
    if not targets_str:
        return jsonify({"error": "请输入目标"}), 400
    if scan_state["running"]:
        return jsonify({"error": "已有扫描任务在运行"}), 400
    targets_list = list(targets_str.split(','))
    continuous = data.get("continuous", False)
    ports = parse_ports_spec(data.get("ports", [25565]))
    if not ports:
        return jsonify({"error": "端口格式无效，请输入如 25565 或 25565-25575"}), 400
    excluder = Excluder(data.get("exclude_file", "exclude.conf"))
    try:
        parsed_raw = list(parse_targets(targets_list, ports))
    except Exception as e:
        return jsonify({"error": f"目标解析失败: {e}"}), 400
    parsed = list(excluder.filter_targets(parsed_raw))
    if not parsed:
        if not parsed_raw:
            return jsonify({"error": "没有有效的目标，请检查输入格式（如 1.2.3.4 或 1.2.3.0/24）"}), 400
        return jsonify({"error": f"目标被排除列表全部过滤（原始{len(parsed_raw)}个，排除后0个）"}), 400
    config = {
        "workers": data.get("workers", 32),
        "timeout": data.get("timeout", 4.0),
        "scan_threads": data.get("scan_threads", 200),
        "scan_timeout": data.get("scan_timeout", 2.5),
        "rate": data.get("rate", 0),
        "auth_check": data.get("auth_check", True),
        "db_path": data.get("db_path", "mcscanner.db"),
        "use_masscan": data.get("use_masscan", False),
        "portscan_only": data.get("portscan_only", False),
        "masscan_rate": data.get("masscan_rate", 5000),
        "ports": ports,
        "exclude_file": data.get("exclude_file", "exclude.conf"),
        "continuous": continuous,
        "async_mode": data.get("async_mode", True),
    }
    t = threading.Thread(target=_scan_worker, args=(parsed, config), daemon=True)
    t.start()
    return jsonify({"status": "started", "targets": len(parsed), "task_id": task_counter + 1})


@app.route('/api/scan/random', methods=['POST'])
def random_scan_api():
    data = request.json or {}
    if scan_state["running"]:
        return jsonify({"error": "已有扫描任务在运行"}), 400
    count = data.get("count", 1000)
    ports = data.get("ports", "25565-25575")
    workers = data.get("workers", 200)
    timeout = data.get("timeout", 2.0)
    do_probe = data.get("probe", True)

    def _random_worker():
        global task_counter
        try:
            task_counter += 1
            with scan_lock:
                scan_state["task_id"] = task_counter
                scan_state["running"] = True
                scan_state["results"] = []
                scan_state["logs"] = []
                scan_state["progress"] = 0
                scan_state["start_time"] = time.time()
            scan_stop_event.clear()
            _log(f"随机暴力扫描开始: {count} 个目标, 端口 {ports}")
            port_ranges = parse_port_ranges(ports)
            def progress(done, total, found):
                with scan_lock:
                    scan_state["progress"] = done
                    scan_state["total"] = total
                    if done % 50 == 0:
                        _log(f"随机扫描进度: {done}/{total}, 发现 {found} 个开放端口")
            open_ports = random_scan(count, workers, timeout, port_ranges, progress)
            _log(f"随机扫描完成: 发现 {len(open_ports)} 个开放端口")
            if do_probe and open_ports:
                _log(f"开始 SLP 探测 {len(open_ports)} 个目标...")
                engine = ScanEngine(stop_event=scan_stop_event, workers=min(32, workers), timeout=3.0)
                results = engine.probe_list(open_ports)
                with scan_lock:
                    scan_state["results"] = results
                    scan_state["progress"] = len(results)
                    scan_state["total"] = len(results)
                _log(f"SLP 探测完成: 发现 {len(results)} 个 MC 服务器")
            else:
                results = [{"ip": ip, "port": port, "auth": "unknown", "version": None,
                           "players_online": 0, "players_max": 0, "motd": None}
                          for ip, port in open_ports]
                with scan_lock:
                    scan_state["results"] = results
                    scan_state["progress"] = len(results)
                    scan_state["total"] = len(results)
        except Exception as e:
            _log(f"随机扫描出错: {e}")
        finally:
            with scan_lock:
                scan_state["running"] = False

    t = threading.Thread(target=_random_worker, daemon=True)
    t.start()
    return jsonify({"status": "started", "count": count, "task_id": task_counter + 1})


@app.route('/api/scan/stop', methods=['POST'])
def stop_scan():
    scan_stop_event.set()
    _log("收到停止请求，正在终止扫描...")
    return jsonify({"status": "stop_requested"})


@app.route('/api/scan/status')
def scan_status():
    with scan_lock:
        return jsonify({
            "running": scan_state["running"],
            "progress": scan_state["progress"],
            "total": scan_state["total"],
            "scanned": scan_state.get("scanned", 0),
            "open_count": scan_state.get("open_count", 0),
            "results_count": len(scan_state["results"]),
            "logs": scan_state["logs"][-100:],
            "start_time": scan_state["start_time"],
            "task_id": scan_state["task_id"],
            "elapsed": time.time() - scan_state["start_time"] if scan_state["start_time"] else 0,
            "error": scan_state.get("error", ""),
        })


@app.route('/api/scan/results')
def scan_results():
    auth = request.args.get("auth")
    search = request.args.get("search", "")
    modded = request.args.get("modded")
    core_type = request.args.get("core_type")
    only_online = request.args.get("only_online") == "1"
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    with scan_lock:
        results = list(scan_state["results"])
    filtered = []
    for r in results:
        if auth and r.get("auth") != auth:
            continue
        if modded and str(r.get("is_modded", 0)) != modded:
            continue
        if core_type and r.get("core_type", "") != core_type:
            continue
        if only_online and r.get("players_online", 0) <= 0:
            continue
        if search:
            search_lower = search.lower()
            if (search_lower not in str(r.get("ip", "")).lower()
                    and search_lower not in str(r.get("motd", "")).lower()
                    and search_lower not in str(r.get("version", "")).lower()):
                continue
        filtered.append(r)
    total = len(filtered)
    start = (page - 1) * per_page
    end = start + per_page
    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "results": filtered[start:end],
    })


def _html_escape(s):
    """HTML转义，防止XSS"""
    if s is None:
        return ""
    s = str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


@app.route('/api/scan/export')
def export_results():
    fmt = request.args.get("format", "json")
    auth = request.args.get("auth")
    with scan_lock:
        results = list(scan_state["results"])
    if auth:
        results = [r for r in results if r.get("auth") == auth]
    if fmt == "csv":
        import csv
        def _csv_generator():
            if results:
                keys = list(results[0].keys())
                # 用yield逐行输出，避免大结果集全量进内存
                import io
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=keys)
                writer.writeheader()
                yield output.getvalue()
                for r in results:
                    output = io.StringIO()
                    writer = csv.DictWriter(output, fieldnames=keys)
                    writer.writerow(r)
                    yield output.getvalue()
        return Response(_csv_generator(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=results.csv"})
    elif fmt == "html":
        offline = sum(1 for r in results if r.get("auth") == "offline")
        online = sum(1 for r in results if r.get("auth") == "online")
        whitelist = sum(1 for r in results if r.get("auth") == "whitelist")
        has_players = sum(1 for r in results if r.get("players_online", 0) > 0)
        total_players = sum(r.get("players_online", 0) for r in results)
        versions = {}
        for r in results:
            v = r.get("version") or "未知"
            versions[v] = versions.get(v, 0) + 1
        version_rows = "".join("<tr><td>" + _html_escape(v) + "</td><td>" + str(c) + "</td></tr>" for v, c in sorted(versions.items(), key=lambda x: -x[1]))
        server_rows = ""
        for r in results:
            players = ", ".join(r.get("player_list", [])) or "-"
            server_rows += "<tr><td>" + _html_escape(r.get('ip')) + ":" + _html_escape(r.get('port')) + "</td><td>" + _html_escape(r.get('version','?')) + "</td><td>" + _html_escape(r.get('players_online',0)) + "/" + _html_escape(r.get('players_max',0)) + "</td><td>" + _html_escape(players) + "</td><td>" + _html_escape(r.get('auth','?')) + "</td><td>" + _html_escape((r.get('motd','') or '')[:60]) + "</td></tr>"
        html_content = "<!DOCTYPE html><html><head><meta charset='utf-8'><title>MC Scanner 扫描报告</title>"
        html_content += "<style>body{font-family:sans-serif;max-width:1200px;margin:0 auto;padding:20px;background:#f8fafc;color:#1e293b}"
        html_content += "h1{color:#0f172a;border-bottom:3px solid #3b82f6;padding-bottom:10px}"
        html_content += ".stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:15px;margin:20px 0}"
        html_content += ".stat{background:#fff;border-radius:10px;padding:15px;box-shadow:0 1px 3px rgba(0,0,0,0.1);text-align:center}"
        html_content += ".stat .num{font-size:28px;font-weight:bold;color:#3b82f6}"
        html_content += ".stat .label{font-size:12px;color:#64748b;margin-top:5px}"
        html_content += "table{width:100%;border-collapse:collapse;margin:15px 0;background:#fff;border-radius:8px;overflow:hidden}"
        html_content += "th{background:#3b82f6;color:#fff;padding:10px;text-align:left;font-size:13px}"
        html_content += "td{padding:8px 10px;border-bottom:1px solid #e2e8f0;font-size:12px}"
        html_content += "tr:hover{background:#f1f5f9}h2{color:#334155;margin-top:30px}"
        html_content += ".footer{text-align:center;color:#94a3b8;font-size:11px;margin-top:30px}</style></head><body>"
        html_content += "<h1>MC Scanner v3-3.1 扫描报告</h1><p>生成时间: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + "</p>"
        html_content += "<div class='stats'>"
        html_content += "<div class='stat'><div class='num'>" + str(len(results)) + "</div><div class='label'>总服务器</div></div>"
        html_content += "<div class='stat'><div class='num'>" + str(offline) + "</div><div class='label'>离线模式</div></div>"
        html_content += "<div class='stat'><div class='num'>" + str(online) + "</div><div class='label'>正版模式</div></div>"
        html_content += "<div class='stat'><div class='num'>" + str(whitelist) + "</div><div class='label'>白名单</div></div>"
        html_content += "<div class='stat'><div class='num'>" + str(has_players) + "</div><div class='label'>有人在线</div></div>"
        html_content += "<div class='stat'><div class='num'>" + str(total_players) + "</div><div class='label'>总玩家数</div></div>"
        html_content += "</div><h2>版本分布</h2><table><tr><th>版本</th><th>数量</th></tr>" + version_rows + "</table>"
        html_content += "<h2>服务器列表</h2><table><tr><th>地址</th><th>版本</th><th>人数</th><th>在线玩家</th><th>认证</th><th>MOTD</th></tr>" + server_rows + "</table>"
        html_content += "<div class='footer'>MC Scanner v3-3.1 | 扫描报告自动生成</div></body></html>"
        return Response(html_content, mimetype="text/html",
                        headers={"Content-Disposition": "attachment; filename=mcscanner_report.html"})
    else:
        return Response(json.dumps(results, ensure_ascii=False, indent=2),
                        mimetype="application/json",
                        headers={"Content-Disposition": "attachment; filename=results.json"})


@app.route('/api/warn/single', methods=['POST'])
def warn_single():
    data = request.json or {}
    ip = data.get("ip")
    port = int(data.get("port") or 25565)
    username = data.get("username", "SecurityBot")
    messages = data.get("messages") or DEFAULT_WARNING_MESSAGES
    authme_password = data.get("authme_password")
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
                            authme_password=authme_password)
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
    data = request.json or {}
    targets_raw = data.get("targets", [])
    username = data.get("username", "SecurityBot")
    messages = data.get("messages") or DEFAULT_WARNING_MESSAGES
    workers = int(data.get("workers", 5))
    authme_password = data.get("authme_password")
    message_delay = float(data.get("message_delay", 0.8))

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
                              15.0, message_delay, proto or None, authme_password): (ip, port)
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
    data = request.json or {}
    targets_raw = data.get("targets", [])
    bot_count = int(data.get("bot_count", 5))
    name_prefix = data.get("name_prefix", "SecurityBot")
    messages = data.get("messages") or DEFAULT_WARNING_MESSAGES
    message_delay = float(data.get("message_delay", 0.5))
    authme_password = data.get("authme_password")
    workers = int(data.get("workers", 20))

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
    if bot_count < 1 or bot_count > 50:
        return jsonify({"error": "机器人数量需在 1-50 之间"}), 400

    _log(f"多机器人警告开始：{len(targets)}台服务器 x {bot_count}个机器人")

    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = []

    def run_bot(ip, port, proto, idx):
        name = f"{name_prefix}_{idx:02d}"
        try:
            # 连接节流保护：1.12.2等旧版服务器默认 connection-throttle=4000ms
            # 同一IP 4秒内只能连一次，按编号错开连接时间
            if idx > 1:
                time.sleep(4.5 * (idx - 1))
            r = join_and_warn(ip, port, name, messages, timeout=15.0,
                              message_delay=message_delay,
                              protocol_version=proto or None,
                              authme_password=authme_password)
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


# ===== 新增：导入 masscan 结果 =====
@app.route('/api/import', methods=['POST'])
def import_masscan_results():
    if 'file' not in request.files:
        return jsonify({"error": "请选择文件"}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({"error": "文件名为空"}), 400
    do_auth = request.form.get('do_auth', '1') == '1'
    tmp_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'import_' + str(int(time.time())) + '.ndjson')
    f.save(tmp_path)
    _log(f"导入 masscan 结果: {f.filename}")
    try:
        if do_auth:
            engine = ScanEngine(stop_event=scan_stop_event, db_path="mcscanner.db", workers=32, timeout=4.0, auth_check=True)
            results = engine.import_masscan(tmp_path, then_auth=True)
        else:
            raw = parse_masscan_json(tmp_path)
            results = [{"ip": ip, "port": port, "auth": "unknown",
                        "version": None, "motd": None,
                        "players_online": 0, "players_max": 0,
                        "ping_ms": None, "proto": None}
                       for ip, port, _ in raw]
        with scan_lock:
            scan_state["results"] = results
            scan_state["progress"] = 100
            scan_state["total"] = len(results)
        _log(f"导入完成，共 {len(results)} 个服务器")
        return jsonify({"status": "ok", "count": len(results)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ===== 新增：给服务器发命令 =====
@app.route('/api/bot/command', methods=['POST'])
def bot_command():
    data = request.json or {}
    ip = data.get("ip")
    port = int(data.get("port") or 25565)
    username = data.get("username", "SecurityBot")
    command = data.get("command", "")
    authme_password = data.get("authme_password")
    hold = float(data.get("hold", 6.0))
    if not ip or not command:
        return jsonify({"error": "IP 和命令不能为空"}), 400
    try:
        bot = MCBot(host=ip, port=port, username=username)
        bot.connect()
        if authme_password:
            bot.authme_login(authme_password, register=False)
            time.sleep(1.0)
        before = len(bot.chat_messages)
        bot.send_command(command)
        time.sleep(1.5)  # 等服务器处理命令
        bot.keep_alive(hold)
        auth_mode = getattr(bot, 'auth_mode', 'unknown')
        state = getattr(bot, 'state', 'unknown')
        # 收集命令发送后收到的新聊天消息作为响应
        chat_responses = bot.chat_messages[before:]
        bot.close()
        cmd = command if command.startswith('/') else '/' + command
        return jsonify({"success": True, "command": cmd, "auth_mode": auth_mode,
                        "state": state, "hold": hold, "chat": chat_responses[-10:]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ===== 新增：生成协议表 =====
@app.route('/api/tools/gen_packets', methods=['POST'])
def gen_packets():
    data = request.json or {}
    download = data.get("download", False)
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
        import gen_packets as gp
        if hasattr(gp, 'main'):
            gp.main()
        return jsonify({"success": True, "message": "协议表生成完成"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ===== 新增：masscan 状态检查 =====
@app.route('/api/masscan/status')
def masscan_status():
    return jsonify({
        "available": has_masscan(),
        "version": get_masscan_version() or "unknown",
    })


@app.route('/api/db/query')
def db_query():
    db_path = _safe_db_path(request.args.get("db_path", "mcscanner.db"))
    auth = request.args.get("auth")
    modded = request.args.get("modded")
    search = request.args.get("search")
    try:
        limit = int(request.args.get("limit", 100))
    except (ValueError, TypeError):
        limit = 100
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    try:
        modded_val = int(modded) if modded else None
    except (ValueError, TypeError):
        modded_val = None
    if not os.path.exists(db_path):
        return jsonify({"total": 0, "results": []})
    rows = db.query(db_path, auth=auth, modded=modded_val,
                     search=search, limit=limit, offset=offset)
    total = db.count(db_path, auth=auth, modded=modded_val, search=search)
    return jsonify({"total": total, "results": rows})


@app.route('/api/db/export')
def db_export():
    """导出扫描数据库，支持 txt/csv/json/html 格式，带筛选条件"""
    db_path = _safe_db_path(request.args.get("db_path", "mcscanner.db"))
    fmt = request.args.get("format", "txt").lower()
    auth = request.args.get("auth")
    modded = request.args.get("modded")
    search = request.args.get("search")
    only_online = request.args.get("only_online", "0")
    try:
        modded_val = int(modded) if modded else None
    except (ValueError, TypeError):
        modded_val = None
    if not os.path.exists(db_path):
        return jsonify({"error": "数据库不存在"}), 404

    # 导出最多20000条，避免文件过大
    rows = db.query(db_path, auth=auth, modded=modded_val, search=search, limit=20000, offset=0)
    if only_online == "1":
        rows = [r for r in rows if r.get("players_online", 0) > 0]
    total = len(rows)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ts = int(time.time())

    if fmt == "json":
        return jsonify({"total": total, "exported_at": now, "results": rows})

    if fmt == "csv":
        lines = ["IP,端口,版本,协议,人数,延迟,验证,核心,Mod,MOTD"]
        for r in rows:
            ip = r.get("ip", "")
            port = r.get("port", 25565)
            ver = (r.get("version") or "").replace(",", " ")
            proto = r.get("proto", "")
            players = f"{r.get('players_online', 0)}/{r.get('players_max', 0)}"
            ping = r.get("ping_ms", "")
            auth_v = r.get("auth", "")
            core = (r.get("core_type") or "").replace(",", " ")
            mods = "是" if r.get("is_modded") else "否"
            motd = (r.get("motd") or "").replace(",", " ").replace("\n", " ")
            lines.append(f"{ip},{port},{ver},{proto},{players},{ping},{auth_v},{core},{mods},{motd}")
        return Response("\n".join(lines), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=scan_results_{ts}.csv"})

    if fmt == "html":
        rows_html = ""
        for r in rows:
            ip = r.get("ip", "")
            port = r.get("port", 25565)
            ver = r.get("version") or "-"
            players = f"{r.get('players_online', 0)}/{r.get('players_max', 0)}"
            online = r.get("players_online", 0)
            pcolor = "#e94560" if online > 0 else "#555"
            auth_v = r.get("auth") or "-"
            core = r.get("core_type") or "-"
            motd = (r.get("motd") or "")[:50]
            rows_html += f"""<tr>
<td><a href="http://{ip}:{port}" style="color:#00d992;">{ip}:{port}</a></td>
<td>{ver}</td><td style="color:{pcolor};font-weight:bold;">{players}</td><td>{auth_v}</td><td>{core}</td><td style="color:#888;font-size:12px;">{motd}</td>
</tr>"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>扫描结果导出</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0a0a0a;color:#e0e0e0;font-family:Consolas,Monaco,monospace;padding:20px}}
.container{{max-width:1100px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #0f3460;border-radius:12px;padding:24px;margin-bottom:20px}}
.header h1{{color:#00d992;font-size:22px;margin-bottom:8px}}
.header .info{{color:#888;font-size:13px}}.header .info span{{color:#e94560}}
table{{width:100%;border-collapse:collapse;background:#111;border:1px solid #222;border-radius:12px;overflow:hidden}}
th{{background:#0f3460;color:#fff;padding:10px;text-align:left;font-size:13px}}
td{{padding:8px 10px;border-bottom:1px solid #1a1a1a;font-size:13px}}
tr:hover{{background:#161616}}
.footer{{text-align:center;color:#444;font-size:12px;margin-top:16px}}</style>
</head><body><div class="container">
<div class="header"><h1>MC扫描结果</h1>
<div class="info">共 <span>{total}</span> 个服务器 | 导出时间: <span>{now}</span></div>
</div>
<table><tr><th>地址</th><th>版本</th><th>人数</th><th>验证</th><th>核心</th><th>MOTD</th></tr>{rows_html}</table>
<div class="footer">Generated by mc-scanner-v3</div>
</div></body></html>"""
        return Response(html, mimetype="text/html; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=scan_results_{ts}.html"})

    # 默认 TXT
    lines = [f"MC扫描结果导出", f"共 {total} 个服务器", f"导出时间: {now}", "=" * 60, ""]
    for i, r in enumerate(rows, 1):
        ip = r.get("ip", "")
        port = r.get("port", 25565)
        ver = r.get("version") or "?"
        players = f"{r.get('players_online', 0)}/{r.get('players_max', 0)}"
        auth_v = r.get("auth") or "?"
        core = r.get("core_type") or "?"
        motd = (r.get("motd") or "")[:60]
        lines.append(f"[{i}] {ip}:{port}")
        lines.append(f"    版本: {ver} | 人数: {players} | 验证: {auth_v} | 核心: {core}")
        if motd:
            lines.append(f"    MOTD: {motd}")
        lines.append("")
    return Response("\n".join(lines), mimetype="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=scan_results_{ts}.txt"})


@app.route('/api/server/popularity')
def server_popularity():
    """查询服务器人数历史趋势"""
    ip = request.args.get("ip", "")
    port = request.args.get("port", type=int)
    hours = request.args.get("hours", type=int, default=24)
    if not ip or not port:
        return jsonify({"error": "ip和port必填"}), 400
    db_path = _safe_db_path(request.args.get("db_path", "mcscanner.db"))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # 按小时聚合，取每小时最大人数
    rows = conn.execute(
        """SELECT strftime('%Y-%m-%d %H:00', recorded_at) as hour,
                  MAX(players_online) as online, MAX(players_max) as max_p
           FROM server_popularity
           WHERE ip=? AND port=? AND recorded_at > datetime('now', ?)
           GROUP BY hour ORDER BY hour ASC""",
        (ip, port, f'-{hours} hours')
    ).fetchall()
    conn.close()
    return jsonify({
        "ip": ip, "port": port, "hours": hours,
        "data": [{"time": r["hour"], "online": r["online"], "max": r["max_p"]} for r in rows]
    })


@app.route('/api/db/stats')
def db_stats():
    db_path = _safe_db_path(request.args.get("db_path", "mcscanner.db"))
    if not os.path.exists(db_path):
        return jsonify({"total": 0, "by_auth": {}, "online_servers": 0, "by_version": {}})
    return jsonify(db.stats(db_path))


@app.route('/api/db/rescan', methods=['POST'])
def db_rescan():
    """数据库一键重新探查：对选中服务器重新SLP探测并更新数据库"""
    data = request.json or {}
    targets_raw = data.get("targets", [])
    db_path = _safe_db_path(data.get("db_path", "mcscanner.db"))
    workers = int(data.get("workers", 10))

    targets = []
    for t in targets_raw:
        if isinstance(t, dict):
            targets.append((t["ip"], int(t.get("port", 25565))))
        elif isinstance(t, str) and ":" in t:
            ip, port = t.rsplit(":", 1)
            targets.append((ip, int(port)))
    if not targets:
        return jsonify({"error": "请先选择要重新探查的服务器"}), 400

    _log(f"数据库重新探查开始: {len(targets)} 个目标")
    from core.probe import slp_probe, auth_probe
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = []

    def probe_one(ip, port):
        try:
            r = slp_probe(ip, port, timeout=5.0)
            if r and r.get("state") == "up":
                auth = auth_probe(ip, port, r.get("protocol_version", 0))
                r.update(auth)
                r["ip"] = ip
                r["port"] = port
                r["last_updated"] = int(time.time())
                return r
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(probe_one, ip, port): (ip, port) for ip, port in targets}
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)

    if results:
        db.upsert_many(db_path, results)
    up = len(results)
    _log(f"数据库重新探查完成: {len(targets)} 个目标, {up} 个在线, 已更新数据库")
    return jsonify({"total": len(targets), "up": up, "updated": up})


@app.route('/api/db/warn', methods=['POST'])
def db_warn():
    """数据库一键警告：对选中服务器发送警告消息，支持AuthMe"""
    data = request.json or {}
    targets_raw = data.get("targets", [])
    username = data.get("username", "SecurityBot")
    messages = data.get("messages") or DEFAULT_WARNING_MESSAGES
    authme_password = data.get("authme_password")
    workers = int(data.get("workers", 5))
    message_delay = float(data.get("message_delay", 0.8))

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
                              15.0, message_delay, None, authme_password): (ip, port)
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


@app.route('/api/history')
def history():
    with scan_lock:
        return jsonify({"history": scan_state["history"]})


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


# ===== AI 内容生成 API =====
@app.route('/api/ai/presets')
def ai_presets():
    from core.ai_generator import get_preset_list
    return jsonify({"presets": get_preset_list()})

@app.route('/api/ai/get')
def ai_get():
    """GET版本，浏览器地址栏直接调用。参数: topic, preset, api_key, base_url, model"""
    topic = request.args.get("topic", "").strip()
    preset = request.args.get("preset", "novel")
    custom_prompt = request.args.get("prompt")
    if not topic and not custom_prompt:
        return jsonify({"success": False, "error": "缺少topic参数，例如: /api/ai/get?topic=李白&preset=celebrity"}), 400
    from core.ai_generator import generate_content
    result = generate_content(
        topic=topic, preset=preset,
        api_key=request.args.get("api_key") or config.get("ai_api_key", ""),
        base_url=request.args.get("base_url") or config.get("ai_base_url", "https://api.openai.com/v1"),
        model=request.args.get("model") or config.get("ai_model", "gpt-3.5-turbo"),
        custom_prompt=custom_prompt,
    )
    # 浏览器直接访问时返回纯文本，方便阅读
    if request.args.get("format") == "text":
        text = result["text"] if result["success"] else f"错误: {result['error']}"
        return Response(text, mimetype="text/plain; charset=utf-8")
    return jsonify(result)

@app.route('/api/ai/generate', methods=['POST'])
def ai_generate():
    data = request.json or {}
    topic = data.get("topic", "").strip()
    preset = data.get("preset", "novel")
    custom_prompt = data.get("custom_prompt")
    custom_system = data.get("custom_system")
    if not topic and not custom_prompt:
        return jsonify({"success": False, "error": "请输入主题或自定义提示词"}), 400
    from core.ai_generator import generate_content
    cfg = config.get("ai_api_key", "")
    result = generate_content(
        topic=topic, preset=preset,
        api_key=data.get("api_key") or cfg,
        base_url=data.get("base_url") or config.get("ai_base_url", "https://api.openai.com/v1"),
        model=data.get("model") or config.get("ai_model", "gpt-3.5-turbo"),
        custom_prompt=custom_prompt, custom_system=custom_system,
    )
    return jsonify(result)

@app.route('/api/ai/send', methods=['POST'])
def ai_send():
    """AI生成内容并发送到指定服务器"""
    data = request.json or {}
    ip = data.get("ip")
    port = int(data.get("port") or 25565)
    username = data.get("username", "StoryBot")
    authme_password = data.get("authme_password")
    if not ip:
        return jsonify({"success": False, "error": "请指定服务器地址"}), 400
    # 先生成
    from core.ai_generator import generate_content
    gen = generate_content(
        topic=data.get("topic", ""), preset=data.get("preset", "novel"),
        api_key=data.get("api_key") or config.get("ai_api_key", ""),
        base_url=data.get("base_url") or config.get("ai_base_url", "https://api.openai.com/v1"),
        model=data.get("model") or config.get("ai_model", "gpt-3.5-turbo"),
        custom_prompt=data.get("custom_prompt"),
    )
    if not gen["success"]:
        return jsonify({"success": False, "error": gen["error"]})
    # 再发送
    from core.bot import join_and_warn
    messages = gen["segments"]
    _log(f"AI生成并发送: {len(messages)}段 -> {ip}:{port}")
    r = join_and_warn(ip, port, username, messages, timeout=15.0,
                      message_delay=float(data.get("message_delay", 1.0)),
                      authme_password=authme_password)
    return jsonify({
        "success": r.success, "messages_sent": r.messages_sent,
        "total_segments": len(messages), "text": gen["text"],
        "segments": gen["segments"], "error": r.error,
    })


# ===== 收藏管理 API =====
@app.route('/api/favorites')
def fav_list():
    tag = request.args.get("tag")
    search = request.args.get("search", "")
    favs = favorites.filter_favorites(tag=tag or None, search=search or None)
    return jsonify({"total": len(favs), "favorites": favs, "tags": favorites.get_all_tags()})

@app.route('/api/favorites/add', methods=['POST'])
def fav_add():
    data = request.json or {}
    ip = data.get("ip")
    port = int(data.get("port") or 25565)
    tags = data.get("tags", [])
    note = data.get("note", "")
    info = data.get("info")
    if not ip:
        return jsonify({"error": "IP 不能为空"}), 400
    fav = favorites.add_favorite(ip, port, tags=tags, note=note, info=info)
    _log(f"收藏添加: {ip}:{port}")
    return jsonify({"success": True, "favorite": fav})

@app.route('/api/favorites/remove', methods=['POST'])
def fav_remove():
    data = request.json or {}
    ip = data.get("ip")
    port = int(data.get("port") or 25565)
    ok = favorites.remove_favorite(ip, port)
    if ok:
        _log(f"收藏移除: {ip}:{port}")
    return jsonify({"success": ok})

@app.route('/api/favorites/tags', methods=['POST'])
def fav_tags():
    data = request.json or {}
    ip = data.get("ip")
    port = int(data.get("port") or 25565)
    tags = data.get("tags", [])
    fav = favorites.update_tags(ip, port, tags)
    return jsonify({"success": fav is not None, "favorite": fav})

@app.route('/api/favorites/note', methods=['POST'])
def fav_note():
    data = request.json or {}
    ip = data.get("ip")
    port = int(data.get("port") or 25565)
    note = data.get("note", "")
    fav = favorites.update_note(ip, port, note)
    return jsonify({"success": fav is not None, "favorite": fav})

@app.route('/api/favorites/rescan', methods=['POST'])
def fav_rescan():
    data = request.json or {}
    timeout = float(data.get("timeout", 5.0))
    workers = int(data.get("workers", 10))
    def _progress(done, total):
        _log(f"收藏重查进度: {done}/{total}")
    favs = favorites.rescan_all(timeout=timeout, workers=workers, progress_callback=_progress)
    _log(f"收藏重查完成: {len(favs)} 个")
    return jsonify({"success": True, "total": len(favs), "favorites": favs})

@app.route('/api/favorites/rescan_one', methods=['POST'])
def fav_rescan_one():
    data = request.json or {}
    ip = data.get("ip")
    port = int(data.get("port") or 25565)
    info = favorites.rescan_one(ip, port, timeout=float(data.get("timeout", 5.0)))
    return jsonify({"success": True, "info": info})

@app.route('/api/favorites/import', methods=['POST'])
def fav_import():
    if 'file' not in request.files:
        return jsonify({"error": "请选择文件"}), 400
    f = request.files['file']
    tmp_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'fav_import_' + str(int(time.time())) + '.txt')
    f.save(tmp_path)
    try:
        count = favorites.import_from_file(tmp_path)
        _log(f"收藏导入: {count} 个")
        return jsonify({"success": True, "count": count})
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.route('/api/favorites/export')
def fav_export():
    """导出收藏列表，支持 txt/csv/json/html 格式"""
    fmt = request.args.get("format", "txt").lower()
    tag = request.args.get("tag")
    search = request.args.get("search", "")
    favs = favorites.filter_favorites(tag=tag or None, search=search or None)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ts = int(time.time())

    if fmt == "json":
        return jsonify({"total": len(favs), "exported_at": now, "favorites": favs})

    if fmt == "csv":
        lines = ["IP,端口,版本,人数,验证,标签,备注,MOTD"]
        for f in favs:
            info = f.get("last_info") or {}
            ip = f.get("ip", "")
            port = f.get("port", 25565)
            ver = (info.get("version") or "").replace(",", " ")
            players = f"{info.get('players_online', 0)}/{info.get('players_max', 0)}"
            auth = info.get("auth", "")
            tags = "|".join(f.get("tags", []))
            note = (f.get("note") or "").replace(",", " ").replace("\n", " ")
            motd = (info.get("motd") or "").replace(",", " ").replace("\n", " ")
            lines.append(f"{ip},{port},{ver},{players},{auth},{tags},{note},{motd}")
        return Response("\n".join(lines), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=favorites_{ts}.csv"})

    if fmt == "html":
        rows = ""
        for f in favs:
            info = f.get("last_info") or {}
            ip = f.get("ip", "")
            port = f.get("port", 25565)
            ver = info.get("version") or "-"
            players = f"{info.get('players_online', 0)}/{info.get('players_max', 0)}"
            auth = info.get("auth") or "-"
            tags = " ".join(f'<span style="background:#0f3460;padding:2px 6px;border-radius:3px;font-size:11px;">{t}</span>' for t in f.get("tags", []))
            note = f.get("note") or ""
            motd = (info.get("motd") or "")[:50]
            rows += f"""<tr>
<td><a href="http://{ip}:{port}" style="color:#00d992;">{ip}:{port}</a></td>
<td>{ver}</td><td>{players}</td><td>{auth}</td><td>{tags}</td><td>{note}</td><td style="color:#888;font-size:12px;">{motd}</td>
</tr>"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>收藏列表导出</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0a0a0a;color:#e0e0e0;font-family:Consolas,Monaco,monospace;padding:20px}}
.container{{max-width:1100px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #0f3460;border-radius:12px;padding:24px;margin-bottom:20px}}
.header h1{{color:#00d992;font-size:22px;margin-bottom:8px}}
.header .info{{color:#888;font-size:13px}}.header .info span{{color:#e94560}}
table{{width:100%;border-collapse:collapse;background:#111;border:1px solid #222;border-radius:12px;overflow:hidden}}
th{{background:#0f3460;color:#fff;padding:10px;text-align:left;font-size:13px}}
td{{padding:8px 10px;border-bottom:1px solid #1a1a1a;font-size:13px}}
tr:hover{{background:#161616}}
.footer{{text-align:center;color:#444;font-size:12px;margin-top:16px}}</style>
</head><body><div class="container">
<div class="header"><h1>MC服务器收藏列表</h1>
<div class="info">共 <span>{len(favs)}</span> 个服务器 | 导出时间: <span>{now}</span></div>
</div>
<table><tr><th>地址</th><th>版本</th><th>人数</th><th>验证</th><th>标签</th><th>备注</th><th>MOTD</th></tr>{rows}</table>
<div class="footer">Generated by mc-scanner-v3</div>
</div></body></html>"""
        return Response(html, mimetype="text/html; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=favorites_{ts}.html"})

    # 默认 TXT
    lines = [f"MC服务器收藏列表", f"共 {len(favs)} 个服务器", f"导出时间: {now}", "=" * 60, ""]
    for i, f in enumerate(favs, 1):
        info = f.get("last_info") or {}
        ip = f.get("ip", "")
        port = f.get("port", 25565)
        ver = info.get("version") or "?"
        players = f"{info.get('players_online', 0)}/{info.get('players_max', 0)}"
        auth = info.get("auth") or "?"
        tags = ",".join(f.get("tags", []))
        note = f.get("note") or ""
        motd = (info.get("motd") or "")[:60]
        lines.append(f"[{i}] {ip}:{port}")
        lines.append(f"    版本: {ver} | 人数: {players} | 验证: {auth}")
        if tags:
            lines.append(f"    标签: {tags}")
        if note:
            lines.append(f"    备注: {note}")
        if motd:
            lines.append(f"    MOTD: {motd}")
        lines.append("")
    return Response("\n".join(lines), mimetype="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=favorites_{ts}.txt"})


# ===== v3.2.1 新增：玩家历史 API =====
@app.route('/api/players')
def players_history():
    db_path = request.args.get("db_path", "mcscanner.db")
    player_name = request.args.get("name")
    ip = request.args.get("ip")
    port = request.args.get("port", type=int)
    limit = int(request.args.get("limit", 100))
    if not os.path.exists(db_path):
        return jsonify({"total": 0, "players": []})
    from storage import player_history as ph
    players = ph.get_player_history(db_path, player_name=player_name, ip=ip, port=port, limit=limit)
    return jsonify({"total": len(players), "players": players})

@app.route('/api/players/stats')
def players_stats():
    db_path = request.args.get("db_path", "mcscanner.db")
    if not os.path.exists(db_path):
        return jsonify({"total_records": 0, "unique_players": 0, "unique_servers": 0})
    from storage import player_history as ph
    return jsonify(ph.get_stats(db_path))

# ===== v3.2.1 新增：智能重扫 API =====
@app.route('/api/rescan')
def rescan_list():
    db_path = request.args.get("db_path", "mcscanner.db")
    action = request.args.get("action", "list")
    limit = int(request.args.get("limit", 100))
    from storage import rescan as rescan_db
    rescan_db.init_rescan_queue(db_path)
    if action == "stats":
        return jsonify(rescan_db.get_stats(db_path))
    if action == "due":
        due = rescan_db.get_due_rescans(db_path, limit=limit)
        return jsonify({"total": len(due), "items": due})
    all_items = rescan_db.get_all_rescans(db_path, limit=limit)
    return jsonify({"total": len(all_items), "items": all_items, "stats": rescan_db.get_stats(db_path)})

@app.route('/api/rescan/run', methods=['POST'])
def rescan_run():
    data = request.json or {}
    db_path = data.get("db_path", "mcscanner.db")
    limit = int(data.get("limit", 50))
    from storage import rescan as rescan_db
    from scanner.engine import ScanEngine
    rescan_db.init_rescan_queue(db_path)
    due = rescan_db.get_due_rescans(db_path, limit=limit)
    if not due:
        return jsonify({"status": "no_due", "count": 0})
    _log(f"智能重扫开始: {len(due)} 个到期目标")
    engine = ScanEngine(db_path=db_path, workers=16, timeout=4.0, rescan_enabled=True)
    results = []
    for item in due:
        try:
            r = engine.probe_one(item["ip"], item["port"])
            results.append(r)
        except Exception:
            continue
    up = sum(1 for r in results if r.get("state") == "up")
    _log(f"智能重扫完成: {len(results)} 个目标, {up} 个在线")
    return jsonify({"status": "completed", "total": len(results), "up": up})

@app.route('/api/rescan/clear', methods=['POST'])
def rescan_clear():
    data = request.json or {}
    db_path = data.get("db_path", "mcscanner.db")
    from storage import rescan as rescan_db
    rescan_db.clear_rescan(db_path)
    _log("重扫队列已清空")
    return jsonify({"success": True})


# ===== v3.3 新增：代理管理 API =====
@app.route('/api/proxy')
def proxy_list():
    from core.proxy import ProxyManager
    manager = ProxyManager(proxy_file="proxies.txt", auto_fetch=False)
    proxies = [{"proto": p.proto, "host": p.host, "port": p.port,
                "fail_count": p.fail_count, "last_used": p.last_used}
               for p in getattr(manager, 'proxies', [])]
    return jsonify({"total": len(proxies), "proxies": proxies})

@app.route('/api/proxy/fetch', methods=['POST'])
def proxy_fetch():
    data = request.json or {}
    from core.proxy import ProxyManager
    manager = ProxyManager(proxy_file="proxies.txt", auto_fetch=False)
    count = manager.fetch_from_api(fetch_socks5=data.get("socks5", False))
    _log(f"代理获取: {count} 个")
    return jsonify({"success": True, "count": count})

@app.route('/api/proxy/check', methods=['POST'])
def proxy_check():
    data = request.json or {}
    from core.proxy import ProxyManager
    manager = ProxyManager(proxy_file="proxies.txt", auto_fetch=False)
    alive = manager.health_check(
        test_host=data.get("test_host", "mc.hypixel.net"),
        test_port=data.get("test_port", 25565),
        timeout=data.get("timeout", 5.0))
    _log(f"代理健康检查: {alive}/{len(manager)} 可用")
    return jsonify({"success": True, "alive": alive, "total": len(manager)})

# ===== v3.3 新增：RCON API =====
@app.route('/api/rcon/execute', methods=['POST'])
def rcon_execute_api():
    data = request.json or {}
    host = data.get("host")
    port = int(data.get("port", 25575))
    password = data.get("password", "")
    command = data.get("command", "")
    if not host or not command:
        return jsonify({"error": "host 和 command 不能为空"}), 400
    try:
        from core.rcon import rcon_execute
        result = rcon_execute(host, port, password, command, timeout=data.get("timeout", 10.0))
        return jsonify({"success": True, "command": command, "response": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)[:200]})

# ===== v3.3 新增：插件抓取 API =====
@app.route('/api/plugins/capture', methods=['POST'])
def plugins_capture():
    data = request.json or {}
    host = data.get("host")
    port = int(data.get("port") or 25565)
    username = data.get("username", "PluginScanner")
    if not host:
        return jsonify({"error": "host 不能为空"}), 400
    try:
        from core.bot import MCBot
        from core.plugins import capture_plugins
        bot = MCBot(host=host, port=port, username=username)
        bot.connect()
        intel = capture_plugins(bot, wait_time=data.get("wait_time", 2.0))
        bot.close()
        return jsonify({
            "success": True,
            "server_software": intel.server_software,
            "version": intel.server_version,
            "plugins": [{"name": p.name, "version": p.version} for p in intel.plugins],
            "anti_cheat": intel.anti_cheat,
            "raw_text": str(intel.raw_responses)[:500],
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)[:200]})

# ===== v3.3 新增：命令执行 API =====
@app.route('/api/commands/run', methods=['POST'])
def commands_run():
    data = request.json or {}
    host = data.get("host")
    port = int(data.get("port") or 25565)
    username = data.get("username", "CommandBot")
    commands = data.get("commands", [])
    if not host or not commands:
        return jsonify({"error": "host 和 commands 不能为空"}), 400
    try:
        from core.command_runner import CommandScript, CommandRunner
        from core.bot import MCBot
        script = CommandScript(delay=data.get("delay", 1.0))
        for cmd in commands:
            script.add(cmd)
        bot = MCBot(host=host, port=port, username=username)
        bot.connect()
        if data.get("authme_password"):
            bot.authme_login(data["authme_password"])
        runner = CommandRunner(bot, delay=data.get("delay", 1.0), timeout=data.get("timeout", 10.0))
        results = runner.run_script(script)
        bot.close()
        return jsonify({
            "success": True,
            "results": [{"command": r.command, "success": r.success,
                         "response": r.response[:300]} for r in results],
            "summary": runner.get_summary(),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)[:200]})


# ============ AI托管Bot ============
_ai_bots = {}  # session_id -> AIBotSession
_ai_bot_seq = 0

@app.route('/api/ai_bot/start', methods=['POST'])
def ai_bot_start():
    global _ai_bot_seq
    data = request.json or {}
    host = data.get("host")
    port = int(data.get("port") or 25565)
    username = data.get("username", "AI助手")
    if not host:
        return jsonify({"success": False, "error": "请指定服务器地址"}), 400
    _ai_bot_seq += 1
    session_id = f"aibot_{_ai_bot_seq}"
    from core.ai_bot import AIBotSession
    ai_cfg = data.get("ai_config", {})
    # 空值回退到全局设置
    if not ai_cfg.get("api_key"):
        ai_cfg["api_key"] = config.get("ai_api_key", "")
    if not ai_cfg.get("base_url"):
        ai_cfg["base_url"] = config.get("ai_base_url", "https://api.openai.com/v1")
    if not ai_cfg.get("model"):
        ai_cfg["model"] = config.get("ai_model", "gpt-3.5-turbo")
    session = AIBotSession(
        host=host, port=port, username=username,
        authme_password=data.get("authme_password"),
        timeout=float(data.get("timeout", 20.0)),
        duration=float(data.get("duration", 0) or 0),
        protocol_version=data.get("protocol_version"),
        ai_config=ai_cfg,
    )
    session.session_id = session_id
    session.start()
    _ai_bots[session_id] = session
    return jsonify({"success": True, "session_id": session_id})

@app.route('/api/ai_bot/stop', methods=['POST'])
def ai_bot_stop():
    data = request.json or {}
    sid = data.get("session_id")
    if sid in _ai_bots:
        _ai_bots[sid].stop()
        del _ai_bots[sid]
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "会话不存在"}), 404

@app.route('/api/ai_bot/list')
def ai_bot_list():
    return jsonify({"sessions": [s.get_status() for s in _ai_bots.values()]})

@app.route('/api/ai_bot/chat')
def ai_bot_chat():
    sid = request.args.get("session_id")
    since = int(request.args.get("since", 0))
    if sid in _ai_bots:
        return jsonify({"messages": _ai_bots[sid].get_chat(since)})
    return jsonify({"messages": []})

@app.route('/api/ai_bot/send', methods=['POST'])
def ai_bot_send():
    data = request.json or {}
    sid = data.get("session_id")
    msg = data.get("message", "")
    if sid in _ai_bots and msg:
        ok = _ai_bots[sid].send_message(msg)
        return jsonify({"success": ok})
    return jsonify({"success": False, "error": "会话不存在或消息为空"}), 400


# ============ 多AI群聊/吵架 ============
@app.route('/api/ai_multi/start', methods=['POST'])
def ai_multi_start():
    data = request.json or {}
    host = data.get("host")
    port = int(data.get("port") or 25565)
    if not host:
        return jsonify({"success": False, "error": "请指定服务器地址"}), 400
    bot_count = int(data.get("bot_count", 3))
    bot_count = max(2, min(8, bot_count))
    from core.ai_bot import multi_ai_bot
    ai_cfg = data.get("ai_config", {})
    # 空值回退到全局设置
    if not ai_cfg.get("api_key"):
        ai_cfg["api_key"] = config.get("ai_api_key", "")
    if not ai_cfg.get("base_url"):
        ai_cfg["base_url"] = config.get("ai_base_url", "https://api.openai.com/v1")
    if not ai_cfg.get("model"):
        ai_cfg["model"] = config.get("ai_model", "gpt-3.5-turbo")
    group_id = multi_ai_bot.start_group(
        host=host, port=port,
        bot_count=bot_count,
        topic=data.get("topic", ""),
        duration=float(data.get("duration", 0) or 0),
        authme_password=data.get("authme_password"),
        ai_config=ai_cfg,
        persona_indices=data.get("persona_indices"),
    )
    return jsonify({"success": True, "group_id": group_id})

@app.route('/api/ai_multi/stop', methods=['POST'])
def ai_multi_stop():
    data = request.json or {}
    gid = data.get("group_id")
    from core.ai_bot import multi_ai_bot
    ok = multi_ai_bot.stop_group(gid)
    return jsonify({"success": ok})

@app.route('/api/ai_multi/list')
def ai_multi_list():
    from core.ai_bot import multi_ai_bot
    return jsonify({"groups": multi_ai_bot.list_groups()})

@app.route('/api/ai_multi/chat')
def ai_multi_chat():
    gid = request.args.get("group_id")
    since = int(request.args.get("since", 0))
    from core.ai_bot import multi_ai_bot
    return jsonify({"messages": multi_ai_bot.get_group_chat(gid, since)})

@app.route('/api/ai_multi/send', methods=['POST'])
def ai_multi_send():
    data = request.json or {}
    gid = data.get("group_id")
    msg = data.get("message", "")
    from core.ai_bot import multi_ai_bot
    ok = multi_ai_bot.send_to_all(gid, msg)
    return jsonify({"success": ok})

@app.route('/api/ai_multi/personas')
def ai_multi_personas():
    from core.ai_bot import PRESET_PERSONAS
    return jsonify({"personas": [{"name": p["name"], "label": p.get("label", p["name"]), "persona": p["persona"]} for p in PRESET_PERSONAS]})


# ============ 服务器健康监控 ============
health_monitor = {
    "running": False,
    "thread": None,
    "stop_event": threading.Event(),
    "interval": 300,  # 5分钟
    "events": [],     # 监控事件日志
    "last_check": None,
    "status": {}      # ip:port -> {online, players, last_change}
}

def _health_monitor_loop():
    """后台健康监控线程：定期检查收藏的服务器，人数变化时记录，一轮汇总发一封邮件"""
    _log("[健康监控] 启动，间隔5分钟")
    while not health_monitor["stop_event"].is_set():
        # 本轮收集到的上线服务器（用于汇总邮件）
        new_online_servers = []  # [{ip, port, players, player_names, new_players}]
        try:
            # 从收藏列表获取服务器
            targets = []
            try:
                from storage.favorites import filter_favorites
                favs = filter_favorites()
                targets = [(f['ip'], f['port']) for f in favs]
            except Exception:
                # 兜底：直接读文件
                fav_file = 'favorites.json'
                if os.path.exists(fav_file):
                    try:
                        with open(fav_file, 'r', encoding='utf-8') as f:
                            favs = json.load(f)
                        if isinstance(favs, list):
                            targets = [(f['ip'], f['port']) for f in favs]
                        elif isinstance(favs, dict) and 'servers' in favs:
                            targets = [(f['ip'], f['port']) for f in favs['servers']]
                    except Exception:
                        pass
            # 也从数据库取有人过的服务器
            try:
                conn = sqlite3.connect('mcscanner.db')
                rows = conn.execute("SELECT ip, port FROM servers WHERE players_online > 0 LIMIT 20").fetchall()
                conn.close()
                for ip, port in rows:
                    if (ip, port) not in targets:
                        targets.append((ip, port))
            except Exception:
                pass

            for ip, port in targets:
                if health_monitor["stop_event"].is_set():
                    break
                try:
                    import asyncio
                    from scanner.async_probe import async_slp_probe
                    r = asyncio.run(async_slp_probe(ip, port, timeout=4))
                    key = f"{ip}:{port}"
                    online = r.get('online', 0) if r else 0
                    prev = health_monitor["status"].get(key, {})
                    prev_online = prev.get('players', 0)
                    # 获取玩家列表
                    player_names = []
                    if r:
                        sample = r.get('sample', [])
                        if isinstance(sample, list):
                            player_names = [p.get('name', '') for p in sample if isinstance(p, dict) and p.get('name')]
                    # 记录人数趋势
                    if r and online > 0:
                        try:
                            conn = sqlite3.connect('mcscanner.db')
                            conn.execute(
                                'INSERT INTO server_popularity (ip, port, players_online, players_max, recorded_at) VALUES (?,?,?,?,?)',
                                (ip, port, online, r.get('max', 0), datetime.now(timezone.utc).isoformat())
                            )
                            conn.commit()
                            conn.close()
                        except Exception:
                            pass
                    # 检测变化
                    if online != prev_online:
                        event = {
                            "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            "ip": ip, "port": port,
                            "from": prev_online, "to": online,
                            "type": "up" if online > prev_online else "down"
                        }
                        health_monitor["events"].insert(0, event)
                        health_monitor["events"] = health_monitor["events"][:100]
                        # 有人上线（从0到>0）收集起来，一轮结束后汇总发邮件
                        if prev_online == 0 and online > 0:
                            _log(f"[健康监控] {ip}:{port} 有人上线了! {online}人")
                            # 对比新增玩家
                            prev_players = set(health_monitor.get("last_players", {}).get(key, []))
                            curr_players = set(player_names)
                            new_players = list(curr_players - prev_players)
                            new_online_servers.append({
                                "ip": ip, "port": port,
                                "players": online,
                                "player_names": player_names,
                                "new_players": new_players,
                            })
                    # 更新上次玩家列表
                    if "last_players" not in health_monitor:
                        health_monitor["last_players"] = {}
                    health_monitor["last_players"][key] = player_names
                    health_monitor["status"][key] = {"online": bool(r), "players": online, "last_check": datetime.now().strftime('%H:%M:%S')}
                except Exception:
                    pass
                time.sleep(0.5)
            health_monitor["last_check"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # 一轮检查结束，汇总发送一封邮件
            if new_online_servers:
                try:
                    from core.notifier import send_email
                    email_enabled = config.get("email_enabled", False)
                    email_to = config.get("email_to", "")
                    if email_enabled and email_to:
                        # 构建邮件内容
                        lines = [f"<h2>服务器上线通知（共{len(new_online_servers)}个）</h2>"]
                        for s in new_online_servers:
                            addr = f"{s['ip']}:{s['port']}"
                            lines.append(f"<p><b>{addr}</b> - {s['players']}人在线</p>")
                            if s['player_names']:
                                lines.append(f"<p style='margin-left:20px;color:#666;'>全部玩家: {', '.join(s['player_names'])}</p>")
                            if s['new_players']:
                                lines.append(f"<p style='margin-left:20px;color:#e94560;'>新增玩家: {', '.join(s['new_players'])}</p>")
                            lines.append("<hr style='border:none;border-top:1px solid #eee;'>")
                        body = "\n".join(lines)
                        ok, err = send_email(
                            f"[MC监控] {len(new_online_servers)}个服务器有人上线了",
                            body, html=True
                        )
                        _log(f"[健康监控] 汇总邮件推送: {len(new_online_servers)}个服, success={ok} error={err}")
                    else:
                        _log(f"[健康监控] 邮件未推送: enabled={email_enabled} to={email_to}")
                except Exception as e:
                    import traceback
                    _log(f"[健康监控] 汇总邮件异常: {e}\n{traceback.format_exc()}")
        except Exception as e:
            _log(f"[健康监控] 错误: {e}")
        # 等待间隔，可被中断
        health_monitor["stop_event"].wait(health_monitor["interval"])

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


# ============ 自动扫描警告 ============
@app.route('/api/auto_scan/tasks')
def auto_scan_tasks():
    from core.auto_scanner import auto_scanner
    return jsonify({"tasks": auto_scanner.list_tasks()})

@app.route('/api/auto_scan/types')
def auto_scan_types():
    from core.auto_scanner import AutoScanner
    return jsonify({"types": [
        {"value": k, "label": v} for k, v in AutoScanner.TASK_TYPES.items()
    ]})

@app.route('/api/auto_scan/add', methods=['POST'])
def auto_scan_add():
    data = request.json or {}
    if not data.get("targets"):
        return jsonify({"success": False, "error": "请指定扫描目标"}), 400
    from core.auto_scanner import auto_scanner
    task_id = auto_scanner.add_task(data)
    if data.get("auto_start", True):
        auto_scanner.start_task(task_id)
    return jsonify({"success": True, "task_id": task_id})

@app.route('/api/auto_scan/start', methods=['POST'])
def auto_scan_start():
    data = request.json or {}
    tid = data.get("task_id")
    from core.auto_scanner import auto_scanner
    ok = auto_scanner.start_task(tid)
    return jsonify({"success": ok})

@app.route('/api/auto_scan/stop', methods=['POST'])
def auto_scan_stop():
    data = request.json or {}
    tid = data.get("task_id")
    from core.auto_scanner import auto_scanner
    auto_scanner.stop_task(tid)
    return jsonify({"success": True})

@app.route('/api/auto_scan/remove', methods=['POST'])
def auto_scan_remove():
    data = request.json or {}
    tid = data.get("task_id")
    from core.auto_scanner import auto_scanner
    auto_scanner.remove_task(tid)
    return jsonify({"success": True})

@app.route('/api/auto_scan/logs')
def auto_scan_logs():
    tid = request.args.get("task_id")
    from core.auto_scanner import auto_scanner
    return jsonify({"logs": auto_scanner.get_logs(tid)})


# ============ AI助手浮窗 ============
@app.route('/api/assistant/chat', methods=['POST'])
def assistant_chat():
    """AI助手：自然语言指令控制扫描器"""
    data = request.json or {}
    msg = (data.get("message", "") or "").strip()
    if not msg:
        return jsonify({"reply": "你说啥？"})

    reply = _handle_assistant_command(msg)
    return jsonify({"reply": reply})


def _handle_assistant_command(msg):
    """解析用户指令并执行，返回自然语言回复"""
    low = msg.lower()
    import re

    # 帮助
    if any(k in msg for k in ["帮助", "能干嘛", "会什么", "怎么用", "help"]):
        return """我能帮你干这些：
📡 扫描：说"扫1.2.3.4"或"扫1.2.3.4端口25565,25566"
⏹ 停止：说"停"或"停止扫描"
📊 进度：说"扫得怎么样"或"进度"
📋 结果：说"结果"或"扫到什么了"
👥 有人的服：说"有人的服务器"或"哪些服有人"
🗄 数据库：说"数据库统计"或"多少个服"
💚 健康监控：说"监控状态"
⭐ 收藏：说"收藏列表"
🤖 AI托管：说"托管1.2.3.4:25565"
直接说就行，不用记命令"""

    # 停止扫描
    if any(k in msg for k in ["停止", "停下", "别扫了", "停"]) and "扫描" in msg or low in ["停", "stop"]:
        try:
            if scan_state["thread"] and scan_state["thread"].is_alive():
                scan_state["stop_event"].set()
                return "好，已停止扫描"
            return "没在扫啊"
        except Exception as e:
            return f"停止失败: {e}"

    # 扫描状态
    if any(k in msg for k in ["进度", "怎么样", "状态", "扫完没"]):
        try:
            st = scan_state
            total = st.get("total", 0)
            done = st.get("done", 0)
            found = st.get("found", 0)
            pct = (done / total * 100) if total else 0
            if st.get("running"):
                return f"扫描中... {done}/{total} ({pct:.1f}%)，已发现 {found} 个MC服"
            elif done > 0:
                return f"扫描完成！共扫 {total} 个目标，发现 {found} 个MC服"
            else:
                return '没在扫描，说"扫IP"开始'
        except Exception as e:
            return f"查询失败: {e}"

    # 扫描结果
    if any(k in msg for k in ["结果", "扫到什么", "有哪些服", "发现了"]):
        try:
            results = scan_state.get("results", [])
            if not results:
                return "还没结果呢，先去扫"
            lines = [f"共发现 {len(results)} 个MC服："]
            for r in results[:15]:
                players = r.get('players_online', 0)
                ver = r.get('version', '')[:20]
                lines.append(f"  {r['ip']}:{r['port']} | {players}人 | {ver}")
            if len(results) > 15:
                lines.append(f"  ...还有 {len(results)-15} 个，去结果页看")
            return "\n".join(lines)
        except Exception as e:
            return f"查询失败: {e}"

    # 有人的服务器
    if any(k in msg for k in ["有人", "活人", "哪些服有玩家", "玩家多的"]):
        try:
            conn = sqlite3.connect('mcscanner.db')
            rows = conn.execute(
                "SELECT ip, port, players_online, version FROM servers WHERE players_online > 0 ORDER BY players_online DESC LIMIT 15"
            ).fetchall()
            conn.close()
            if not rows:
                return "数据库里没人在线的服务器"
            lines = [f"找到 {len(rows)} 个有人的服："]
            for ip, port, players, ver in rows:
                lines.append(f"  {ip}:{port} | {players}人 | {ver or '未知'}")
            return "\n".join(lines)
        except Exception as e:
            return f"查询失败: {e}"

    # 数据库统计
    if any(k in msg for k in ["数据库", "多少个服", "统计", "db"]):
        try:
            conn = sqlite3.connect('mcscanner.db')
            total = conn.execute("SELECT COUNT(*) FROM servers").fetchone()[0]
            online = conn.execute("SELECT COUNT(*) FROM servers WHERE players_online > 0").fetchone()[0]
            cracked = conn.execute("SELECT COUNT(*) FROM servers WHERE auth_mode='offline'").fetchone()[0]
            conn.close()
            return f"数据库共 {total} 个服务器，其中 {online} 个当前有人，{cracked} 个离线服"
        except Exception as e:
            return f"查询失败: {e}"

    # 健康监控状态
    if any(k in msg for k in ["监控", "健康", "推送"]):
        try:
            hm = health_monitor
            events = hm.get("events", [])
            status = hm.get("status", {})
            running = hm.get("running", False)
            lines = [f"健康监控: {'运行中' if running else '未启动'}"]
            lines.append(f"监控 {len(status)} 个服务器，最近检查: {hm.get('last_check', '从未')}")
            if events:
                lines.append(f"最近事件: {events[0].get('time','')} {events[0].get('ip','')}:{events[0].get('port','')} {events[0].get('from','')}→{events[0].get('to','')}人")
            return "\n".join(lines)
        except Exception as e:
            return f"查询失败: {e}"

    # 收藏列表
    if any(k in msg for k in ["收藏", "favorites"]):
        try:
            from storage.favorites import filter_favorites
            favs = filter_favorites()
            if not favs:
                return "收藏夹是空的"
            lines = [f"共收藏 {len(favs)} 个："]
            for f in favs[:15]:
                lines.append(f"  {f['ip']}:{f['port']}")
            return "\n".join(lines)
        except Exception as e:
            return f"查询失败: {e}"

    # 启动扫描：匹配 "扫xxx" 模式
    scan_match = re.search(r'扫[一一下]?\s*([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(?:/[0-9]+)?)\s*(?:端口\s*([0-9, ]+))?', msg)
    if scan_match or ("扫" in msg and re.search(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}', msg)):
        try:
            ip_match = re.search(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(?:/[0-9]+)?', msg)
            target = ip_match.group()
            port_match = re.search(r'端口\s*([0-9, ]+)', msg)
            ports = [int(p.strip()) for p in port_match.group(1).split(',') if p.strip()] if port_match else [25565]
            # 启动扫描（复用现有逻辑）
            from core.engine import ScanEngine
            scan_state["stop_event"].clear()
            scan_state["results"] = []
            scan_state["total"] = 0
            scan_state["done"] = 0
            scan_state["found"] = 0
            scan_state["running"] = True
            scan_state["start_time"] = time.time()

            def _worker():
                try:
                    engine = ScanEngine(
                        targets=[target],
                        ports=ports,
                        db_path="mcscanner.db",
                        concurrency=200,
                        timeout=4.0,
                        result_callback=lambda r: scan_state["results"].append(r) or scan_state.__setitem__("found", scan_state["found"]+1),
                        progress_callback=lambda d, t: (scan_state.__setitem__("done", d), scan_state.__setitem__("total", t)),
                        stop_event=scan_state["stop_event"],
                    )
                    engine.run()
                except Exception as e:
                    print(f"[扫描错误] {e}")
                finally:
                    scan_state["running"] = False

            scan_state["thread"] = threading.Thread(target=_worker, daemon=True)
            scan_state["thread"].start()
            return f'好，开始扫 {target} 端口 {",".join(map(str,ports))}，说"进度"查看'
        except Exception as e:
            return f"启动失败: {e}"

    # AI托管
    if any(k in msg for k in ["托管", "ai进", "bot进"]) and re.search(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}', msg):
        try:
            ip_match = re.search(r'([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}):([0-9]+)', msg)
            if not ip_match:
                return "格式：托管1.2.3.4:25565"
            host, port = ip_match.group(1), int(ip_match.group(2))
            from core.ai_bot import AIBotSession
            global _ai_bot_seq
            _ai_bot_seq += 1
            sid = f"assistant_{_ai_bot_seq}"
            session = AIBotSession(
                host=host, port=port, username="AssistantBot",
                authme_password="AIBot123456", timeout=20, duration=0,
                ai_config={
                    "api_key": config.get("ai_api_key", ""),
                    "base_url": config.get("ai_base_url", "https://api.openai.com/v1"),
                    "model": config.get("ai_model", "gpt-3.5-turbo"),
                    "persona": "你是一个MC玩家，喜欢和人聊天，说话简短有趣，不超过30字。",
                    "reply_enabled": True, "reply_cooldown": 5,
                    "trigger_keywords": [], "auto_talk_enabled": False,
                }
            )
            session.session_id = sid
            session.start()
            _ai_bots[sid] = session
            return f"好，AI已进 {host}:{port}，用户名AssistantBot"
        except Exception as e:
            return f"启动失败: {e}"

    # 没匹配到
    return f'没听懂你说啥。说"帮助"看看我能干嘛。'


def run(db_path: str = "mcscanner.db", port: int = 8080, host: str = "127.0.0.1"):
    logger.setup_logger()
    db.init_db(db_path)
    # 初始化全局代理（如果proxies.txt存在且有代理，自动启用轮换）
    try:
        import os
        from core.proxy import get_proxy_manager
        from core.conn import set_global_proxy_manager
        proxy_file = config.get("proxy_file", "proxies.txt")
        if os.path.exists(proxy_file):
            mgr = get_proxy_manager(proxy_file=proxy_file, auto_fetch=False)
            if mgr and mgr.proxies:
                set_global_proxy_manager(mgr)
                logger.info(f"[*] 已启用代理: {len(mgr.proxies)} 个代理，自动轮换")
    except Exception as e:
        logger.warning(f"[!] 代理初始化失败: {e}")
    logger.info(f"[*] Web 面板启动: http://{host}:{port}")
    logger.info(f"[*] 数据库: {db_path}")
    # 启动健康监控
    if not health_monitor["running"]:
        health_monitor["stop_event"].clear()
        health_monitor["thread"] = threading.Thread(target=_health_monitor_loop, daemon=True)
        health_monitor["thread"].start()
        health_monitor["running"] = True
    # 安全警告：绑定公网且未设置token
    if host in ("0.0.0.0", "::") and not _get_web_token():
        logger.warning("=" * 60)
        logger.warning("[!] 安全警告：绑定 0.0.0.0 且未设置 web_token！")
        logger.warning("[!] 任何人都可访问面板并执行命令/扫描。")
        logger.warning("[!] 请在 config.json 中设置 web_token，或仅绑定 127.0.0.1")
        logger.warning("=" * 60)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run()
