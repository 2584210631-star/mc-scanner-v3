# -*- coding: utf-8 -*-
"""Web 面板共享状态。"""
import threading
from datetime import datetime
import config
import logger

scan_stop_event = threading.Event()
scan_lock = threading.Lock()
task_counter = 0

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

observer_sessions = {}
observer_lock = threading.Lock()

health_monitor = {
    "running": False,
    "thread": None,
    "stop_event": threading.Event(),
    "interval": 300,
    "events": [],
    "last_check": None,
    "status": {},
}

_ai_bots = {}
_ai_bot_seq = 0


def get_web_token():
    return config.get("web_token", "") or ""


def safe_db_path(path: str) -> str:
    if not path:
        return "mcscanner.db"
    if ".." in path or path.startswith("/") or (len(path) >= 2 and path[1] == ":"):
        return "mcscanner.db"
    if not path.endswith(".db"):
        return "mcscanner.db"
    return path


def log_scan(msg: str):
    logger.info(msg)
    with scan_lock:
        entry = {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg}
        scan_state["logs"].append(entry)
        if len(scan_state["logs"]) > 500:
            scan_state["logs"] = scan_state["logs"][-500:]


def parse_ports_spec(ports_spec):
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
    for part in ports_spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start, end = part.split("-", 1)
                start = int(start.strip()); end = int(end.strip())
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
