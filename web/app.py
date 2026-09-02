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
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, Response

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage import db
from scanner.engine import ScanEngine
from scanner.targets import parse_targets, count_targets
from scanner.exclude import Excluder
from scanner.masscan import has_masscan, run_masscan, parse_masscan_json, get_masscan_version
from scanner.portscan import scan_ports, get_open_ports
from core.bot import join_and_warn, DEFAULT_WARNING_MESSAGES, MCBot

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

scan_state = {
    "running": False,
    "progress": 0,
    "total": 0,
    "results": [],
    "logs": [],
    "start_time": None,
    "task_id": None,
    "history": [],
}
scan_lock = threading.Lock()
task_counter = 0


def _log(msg: str):
    with scan_lock:
        entry = {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg}
        scan_state["logs"].append(entry)
        if len(scan_state["logs"]) > 500:
            scan_state["logs"] = scan_state["logs"][-500:]


def _scan_worker(targets_list, config):
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
        _log(f"任务 #{task_counter} 开始，目标数: {len(targets_list)}")

        use_masscan = config.get("use_masscan", False)
        portscan_only = config.get("portscan_only", False)
        results = []

        if use_masscan:
            if not has_masscan():
                _log("masscan 未找到，回退到 Python 扫描")
                use_masscan = False
            else:
                _log(f"使用 masscan 高速扫描，速率: {config.get('masscan_rate', 5000)}/s")
                targets_str = ",".join(str(t) for t in targets_list)
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
                        engine = ScanEngine(
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
                )
                open_ports = get_open_ports(raw_results)
                results = [{"ip": ip, "port": port, "auth": "unknown",
                            "version": None, "motd": None,
                            "players_online": 0, "players_max": 0,
                            "ping_ms": None, "proto": None}
                           for ip, port in open_ports]
                _log(f"端口扫描完成，开放: {len(results)} 个")
            else:
                engine = ScanEngine(
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
                )

        with scan_lock:
            scan_state["results"] = results
            scan_state["progress"] = len(results)
            scan_state["total"] = len(results)
        _log(f"扫描完成，共发现 {len(results)} 个服务器")

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
        _log(f"扫描出错: {e}")
    finally:
        with scan_lock:
            scan_state["running"] = False


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
    excluder = Excluder(data.get("exclude_file", "exclude.conf"))
    parsed = list(excluder.filter_targets(parse_targets(targets_list)))
    if not parsed:
        return jsonify({"error": "没有有效的目标"}), 400
    ports = data.get("ports", [25565])
    if isinstance(ports, str):
        ports = [int(p.strip()) for p in ports.split(',') if p.strip()]
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
    }
    t = threading.Thread(target=_scan_worker, args=(parsed, config), daemon=True)
    t.start()
    return jsonify({"status": "started", "targets": len(parsed), "task_id": task_counter + 1})


@app.route('/api/scan/stop', methods=['POST'])
def stop_scan():
    return jsonify({"status": "stop_requested"})


@app.route('/api/scan/status')
def scan_status():
    with scan_lock:
        return jsonify({
            "running": scan_state["running"],
            "progress": scan_state["progress"],
            "total": scan_state["total"],
            "results_count": len(scan_state["results"]),
            "logs": scan_state["logs"][-100:],
            "start_time": scan_state["start_time"],
            "task_id": scan_state["task_id"],
            "elapsed": time.time() - scan_state["start_time"] if scan_state["start_time"] else 0,
        })


@app.route('/api/scan/results')
def scan_results():
    auth = request.args.get("auth")
    search = request.args.get("search", "")
    modded = request.args.get("modded")
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
        import io
        output = io.StringIO()
        if results:
            keys = list(results[0].keys())
            writer = csv.DictWriter(output, fieldnames=keys)
            writer.writeheader()
            writer.writerows(results)
        return Response(output.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=results.csv"})
    else:
        return Response(json.dumps(results, ensure_ascii=False, indent=2),
                        mimetype="application/json",
                        headers={"Content-Disposition": "attachment; filename=results.json"})


@app.route('/api/warn/single', methods=['POST'])
def warn_single():
    data = request.json or {}
    ip = data.get("ip")
    port = int(data.get("port", 25565))
    username = data.get("username", "SecurityBot")
    messages = data.get("messages") or DEFAULT_WARNING_MESSAGES
    authme_password = data.get("authme_password")
    if not ip:
        return jsonify({"error": "请指定 IP"}), 400
    result = join_and_warn(ip, port, username, messages, timeout=15.0,
                            message_delay=0.8, authme_password=authme_password)
    return jsonify({
        "success": result.success,
        "auth_mode": result.auth_mode,
        "messages_sent": result.messages_sent,
        "error": result.error,
        "version": result.version_name,
    })


@app.route('/api/warn/batch', methods=['POST'])
def warn_batch():
    data = request.json or {}
    auth = data.get("auth", "cracked")
    username = data.get("username", "SecurityBot")
    messages = data.get("messages") or DEFAULT_WARNING_MESSAGES
    workers = data.get("workers", 5)
    with scan_lock:
        targets = [(r["ip"], r["port"]) for r in scan_state["results"]
                   if r.get("auth") == auth]
    if not targets:
        return jsonify({"error": f"没有认证模式为 {auth} 的服务器"}), 400
    _log(f"批量警告开始，目标 {len(targets)} 个服务器")
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(join_and_warn, ip, port, username, messages,
                              15.0, 0.8, None, None): (ip, port)
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
    _log(f"批量警告完成，成功发送 {sent} 条消息")
    return jsonify({"total": len(results), "messages_sent": sent, "results": results})


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
            engine = ScanEngine(db_path="mcscanner.db", workers=32, timeout=4.0, auth_check=True)
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
            scan_state["progress"] = len(results)
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
    port = int(data.get("port", 25565))
    username = data.get("username", "SecurityBot")
    command = data.get("command", "")
    authme_password = data.get("authme_password")
    hold = float(data.get("hold", 3.0))
    if not ip or not command:
        return jsonify({"error": "IP 和命令不能为空"}), 400
    try:
        bot = MCBot()
        bot.connect(ip, port, username)
        bot.login()
        if authme_password:
            bot.authme_login(authme_password, register=False)
        time.sleep(1.0)
        cmd = command if command.startswith('/') else '/' + command
        bot.send_chat(cmd)
        time.sleep(hold)
        bot.disconnect()
        return jsonify({"success": True, "command": cmd, "auth_mode": bot.auth_mode if hasattr(bot, 'auth_mode') else "unknown"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
        "path": __import__('scanner.masscan', fromlist=['get_masscan_path']).get_masscan_path() if hasattr(__import__('scanner.masscan', fromlist=['get_masscan_path']), 'get_masscan_path') else None,
    })


@app.route('/api/db/query')
def db_query():
    db_path = request.args.get("db_path", "mcscanner.db")
    auth = request.args.get("auth")
    modded = request.args.get("modded")
    search = request.args.get("search")
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))
    if not os.path.exists(db_path):
        return jsonify({"total": 0, "results": []})
    rows = db.query(db_path, auth=auth, modded=modded and int(modded),
                     search=search, limit=limit, offset=offset)
    total = db.count(db_path, auth=auth, modded=modded and int(modded), search=search)
    return jsonify({"total": total, "results": rows})


@app.route('/api/db/stats')
def db_stats():
    db_path = request.args.get("db_path", "mcscanner.db")
    if not os.path.exists(db_path):
        return jsonify({"total": 0, "by_auth": {}, "online_servers": 0, "by_version": {}})
    return jsonify(db.stats(db_path))


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


def run(db_path: str = "mcscanner.db", port: int = 8080, host: str = "127.0.0.1"):
    db.init_db(db_path)
    print(f"[*] Web 面板启动: http://{host}:{port}")
    print(f"[*] 数据库: {db_path}")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run()
