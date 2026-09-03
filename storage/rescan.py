# -*- coding: utf-8 -*-
"""
智能重扫队列（v3.2.1 新增，融合 matscan 特性）。
根据服务器状态动态调整重扫频率：
- 有人在线的服务器：5分钟重扫（追踪玩家变化）
- 离线/破解服：30分钟重扫
- 正版/白名单服：2小时重扫
- 新发现服务器：1分钟内快速确认（前5次）
"""
import json
import os
import sqlite3
import time
from datetime import datetime, timezone


RESCAN_QUEUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS rescan_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL,
    port INTEGER NOT NULL,
    strategy TEXT DEFAULT 'default',
    next_scan INTEGER DEFAULT 0,
    scan_count INTEGER DEFAULT 0,
    last_state TEXT DEFAULT '',
    last_auth TEXT DEFAULT '',
    last_online INTEGER DEFAULT 0,
    last_scan INTEGER DEFAULT 0,
    UNIQUE(ip, port)
);
CREATE INDEX IF NOT EXISTS idx_rq_next ON rescan_queue(next_scan);
CREATE INDEX IF NOT EXISTS idx_rq_strategy ON rescan_queue(strategy);
"""

# 重扫策略配置（秒）
DEFAULT_STRATEGIES = {
    "has_players": {"interval": 300, "max_retries": 3, "description": "有人在线，高频重扫"},
    "cracked": {"interval": 1800, "max_retries": 2, "description": "离线/破解服，中等频率"},
    "online": {"interval": 7200, "max_retries": 1, "description": "正版服，低频率"},
    "whitelist": {"interval": 7200, "max_retries": 1, "description": "白名单服，低频率"},
    "new": {"interval": 60, "max_retries": 5, "description": "新发现服务器，快速确认"},
    "default": {"interval": 3600, "max_retries": 1, "description": "默认策略"},
}


def init_rescan_queue(db_path: str):
    """初始化重扫队列表。"""
    conn = sqlite3.connect(db_path)
    conn.executescript(RESCAN_QUEUE_SCHEMA)
    conn.commit()
    conn.close()


def update_rescan(db_path: str, ip: str, port: int, result: dict,
                  strategies: dict = None):
    """
    根据扫描结果更新重扫计划。
    result: {"state", "auth", "players_online", ...}
    """
    strategies = strategies or DEFAULT_STRATEGIES
    now = int(time.time())

    # 确定策略
    strategy_name = _determine_strategy(result, db_path, ip, port)
    strategy = strategies.get(strategy_name, strategies["default"])

    conn = sqlite3.connect(db_path)
    # 检查是否已存在
    row = conn.execute("SELECT scan_count FROM rescan_queue WHERE ip=? AND port=?",
                       (ip, port)).fetchone()
    if row is None:
        # 新发现
        strategy_name = "new"
        strategy = strategies["new"]
        scan_count = 0
    else:
        scan_count = row[0]

    next_scan = now + strategy["interval"]
    conn.execute(
        """INSERT INTO rescan_queue (ip, port, strategy, next_scan, scan_count, last_state, last_auth, last_online, last_scan)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(ip, port) DO UPDATE SET
               strategy=excluded.strategy,
               next_scan=excluded.next_scan,
               scan_count=scan_count+1,
               last_state=excluded.last_state,
               last_auth=excluded.last_auth,
               last_online=excluded.last_online,
               last_scan=excluded.last_scan""",
        (ip, port, strategy_name, next_scan, scan_count + 1,
         result.get("state", ""), result.get("auth", ""),
         result.get("players_online", 0), now)
    )
    conn.commit()
    conn.close()
    return strategy_name


def get_due_rescans(db_path: str, now: int = None, limit: int = 100) -> list:
    """获取到期需要重扫的目标。"""
    if now is None:
        now = int(time.time())
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT ip, port, strategy, scan_count, last_state, last_auth, last_online FROM rescan_queue WHERE next_scan <= ? ORDER BY next_scan ASC LIMIT ?",
        (now, limit)
    ).fetchall()
    conn.close()
    return [{"ip": r[0], "port": r[1], "strategy": r[2], "scan_count": r[3],
             "last_state": r[4], "last_auth": r[5], "last_online": r[6]} for r in rows]


def get_all_rescans(db_path: str, limit: int = 200) -> list:
    """获取全部重扫计划。"""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT ip, port, strategy, next_scan, scan_count, last_state, last_auth, last_online FROM rescan_queue ORDER BY next_scan ASC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [{"ip": r[0], "port": r[1], "strategy": r[2], "next_scan": r[3],
             "scan_count": r[4], "last_state": r[5], "last_auth": r[6], "last_online": r[7]} for r in rows]


def remove_rescan(db_path: str, ip: str, port: int):
    """移除某个目标的重扫计划。"""
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM rescan_queue WHERE ip=? AND port=?", (ip, port))
    conn.commit()
    conn.close()


def clear_rescan(db_path: str):
    """清空重扫队列。"""
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM rescan_queue")
    conn.commit()
    conn.close()


def get_stats(db_path: str) -> dict:
    """获取重扫队列统计。"""
    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM rescan_queue").fetchone()[0]
    by_strategy = {}
    for row in conn.execute("SELECT strategy, COUNT(*) FROM rescan_queue GROUP BY strategy"):
        by_strategy[row[0]] = row[1]
    now = int(time.time())
    due = conn.execute("SELECT COUNT(*) FROM rescan_queue WHERE next_scan <= ?", (now,)).fetchone()[0]
    conn.close()
    return {"total": total, "by_strategy": by_strategy, "due_now": due}


def _determine_strategy(result: dict, db_path: str, ip: str, port: int) -> str:
    """根据扫描结果确定重扫策略。"""
    # 有人在线
    if result.get("players_online", 0) > 0:
        return "has_players"
    # 认证状态
    auth = result.get("auth", "")
    if auth == "cracked":
        return "cracked"
    if auth == "online":
        return "online"
    if auth == "whitelist":
        return "whitelist"
    return "default"
