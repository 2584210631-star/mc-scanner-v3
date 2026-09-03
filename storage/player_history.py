# -*- coding: utf-8 -*-
"""
玩家历史追踪（v3.2.1 新增，融合 matscan 特性）。
记录每个玩家在各服务器的出现/消失/次数，支持按玩家名或服务器查询。
"""
import json
import os
import sqlite3
from datetime import datetime, timezone


PLAYER_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL,
    port INTEGER NOT NULL,
    player_name TEXT NOT NULL,
    player_uuid TEXT DEFAULT '',
    first_seen TEXT,
    last_seen TEXT,
    seen_count INTEGER DEFAULT 1,
    UNIQUE(ip, port, player_name)
);
CREATE INDEX IF NOT EXISTS idx_ph_player ON player_history(player_name);
CREATE INDEX IF NOT EXISTS idx_ph_server ON player_history(ip, port);
CREATE INDEX IF NOT EXISTS idx_ph_last_seen ON player_history(last_seen);
"""


def init_player_history(db_path: str):
    """初始化玩家历史表。"""
    conn = sqlite3.connect(db_path)
    conn.executescript(PLAYER_HISTORY_SCHEMA)
    conn.commit()
    conn.close()


def update_players(db_path: str, ip: str, port: int, player_list: list):
    """
    更新一批玩家的历史记录。
    player_list: [{"name": "...", "id": "..."}, ...] 或 ["name1", "name2", ...]
    """
    if not player_list:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    for player in player_list:
        if isinstance(player, dict):
            name = player.get("name", "")
            uuid = player.get("id", "")
        else:
            name = str(player)
            uuid = ""
        if not name:
            continue
        conn.execute(
            """INSERT INTO player_history (ip, port, player_name, player_uuid, first_seen, last_seen, seen_count)
               VALUES (?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(ip, port, player_name) DO UPDATE SET
                   last_seen=excluded.last_seen,
                   seen_count=seen_count+1,
                   player_uuid=COALESCE(NULLIF(excluded.player_uuid,''), player_uuid)""",
            (ip, port, name, uuid, now, now)
        )
    conn.commit()
    conn.close()


def get_player_history(db_path: str, player_name: str = None,
                        ip: str = None, port: int = None,
                        limit: int = 100, offset: int = 0) -> list:
    """
    查询玩家历史。
    可按玩家名、服务器IP:Port过滤。
    """
    conn = sqlite3.connect(db_path)
    sql = "SELECT * FROM player_history WHERE 1=1"
    args = []
    if player_name:
        sql += " AND player_name LIKE ?"
        args.append(f"%{player_name}%")
    if ip:
        sql += " AND ip = ?"
        args.append(ip)
        if port:
            sql += " AND port = ?"
            args.append(port)
    sql += " ORDER BY last_seen DESC LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    cols = ["id", "ip", "port", "player_name", "player_uuid", "first_seen", "last_seen", "seen_count"]
    return [dict(zip(cols, r)) for r in rows]


def get_unique_players(db_path: str) -> int:
    """获取追踪到的唯一玩家数。"""
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(DISTINCT player_name) FROM player_history").fetchone()[0]
    conn.close()
    return count


def get_player_servers(db_path: str, player_name: str) -> list:
    """获取某个玩家出现过的所有服务器。"""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT ip, port, seen_count, last_seen FROM player_history WHERE player_name = ? ORDER BY last_seen DESC",
        (player_name,)
    ).fetchall()
    conn.close()
    return [{"ip": r[0], "port": r[1], "seen_count": r[2], "last_seen": r[3]} for r in rows]


def get_server_players(db_path: str, ip: str, port: int, limit: int = 50) -> list:
    """获取某台服务器追踪到的所有玩家。"""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT player_name, seen_count, last_seen, first_seen FROM player_history WHERE ip=? AND port=? ORDER BY last_seen DESC LIMIT ?",
        (ip, port, limit)
    ).fetchall()
    conn.close()
    return [{"name": r[0], "seen_count": r[1], "last_seen": r[2], "first_seen": r[3]} for r in rows]


def get_stats(db_path: str) -> dict:
    """获取玩家历史统计。"""
    conn = sqlite3.connect(db_path)
    total_records = conn.execute("SELECT COUNT(*) FROM player_history").fetchone()[0]
    unique_players = conn.execute("SELECT COUNT(DISTINCT player_name) FROM player_history").fetchone()[0]
    unique_servers = conn.execute("SELECT COUNT(DISTINCT ip || ':' || port) FROM player_history").fetchone()[0]
    conn.close()
    return {
        "total_records": total_records,
        "unique_players": unique_players,
        "unique_servers": unique_servers,
    }
