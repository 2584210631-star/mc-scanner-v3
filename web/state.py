# -*- coding: utf-8 -*-
"""Web 面板共享状态。"""
import threading
from datetime import datetime
import config
import logger

scan_stop_event = threading.Event()
scan_lock = threading.Lock()
task_counter = 0

# 任务队列：支持多任务排队，不互相覆盖
scan_tasks = {}          # task_id -> task_state dict
scan_queue = []          # 排队中的 task_id 列表
current_task_id = None   # 当前正在运行的 task_id

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


def new_task_state(task_id, targets_count=0, scan_type="manual"):
    """创建一个新的扫描任务状态"""
    return {
        "task_id": task_id,
        "running": False,
        "status": "queued",  # queued / running / done / stopped / error
        "progress": 0,
        "total": targets_count,
        "scanned": 0,
        "open_count": 0,
        "results": [],
        "logs": [],
        "start_time": None,
        "end_time": None,
        "scan_type": scan_type,
        "stop_event": threading.Event(),
    }


def log_scan(msg: str, task_id=None):
    logger.info(msg)
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg}
    with scan_lock:
        # 写入当前活动任务的日志
        if task_id and task_id in scan_tasks:
            scan_tasks[task_id]["logs"].append(entry)
            if len(scan_tasks[task_id]["logs"]) > 500:
                scan_tasks[task_id]["logs"] = scan_tasks[task_id]["logs"][-500:]
        # 兼容旧接口：写入全局scan_state
        scan_state["logs"].append(entry)
        if len(scan_state["logs"]) > 500:
            scan_state["logs"] = scan_state["logs"][-500:]

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

# 全局安全开关：只读模式下禁止危险操作（警告/进服/扫描）
read_only_mode = False


def is_read_only():
    return read_only_mode or config.get("read_only_mode", False)


def set_read_only(enabled: bool):
    global read_only_mode
    read_only_mode = enabled


def get_web_token():
    return config.get("web_token", "") or ""


def capability_enabled(cap: str) -> bool:
    """能力分级检查：高风险能力默认关闭，需在config.capabilities显式开启。
    cap: 'scan' / 'login_interact' / 'rcon_commands'"""
    caps = config.get("capabilities", {})
    if not isinstance(caps, dict):
        return False
    # scan 默认开启（基础能力），其余默认关闭
    if cap == "scan":
        return bool(caps.get("scan", True))
    return bool(caps.get(cap, False))


def safe_db_path(path: str) -> str:
    if not path:
        return "mcscanner.db"
    if ".." in path or path.startswith("/") or (len(path) >= 2 and path[1] == ":"):
        return "mcscanner.db"
    if not path.endswith(".db"):
        return "mcscanner.db"
    return path


def parse_ports_spec(ports_spec, max_ports=2000):
    """解析端口规格，返回去重排序后的端口列表。max_ports限制单次扫描端口数防滥用。"""
    if ports_spec is None or (isinstance(ports_spec, str) and not ports_spec.strip()):
        return [25565]
    if isinstance(ports_spec, list):
        result = []
        for p in ports_spec:
            result.extend(parse_ports_spec(p, max_ports))
        return sorted(set(result))[:max_ports]
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
    return sorted(set(result))[:max_ports]
