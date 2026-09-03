# -*- coding: utf-8 -*-
"""
SQLite 存储层。
支持去重更新、按认证/模组/核心类型/搜索查询、统计。
v3.1 新增：core_type、mods、forge_channels 字段（自动迁移旧数据库）。
"""
import json
import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS servers (
    ip TEXT,
    port INTEGER,
    version TEXT,
    proto INTEGER,
    motd TEXT,
    is_modded INTEGER,
    players_online INTEGER,
    players_max INTEGER,
    favicon TEXT,
    auth TEXT,
    ping_ms INTEGER,
    json TEXT,
    last_updated TEXT,
    core_type TEXT,
    mods TEXT,
    forge_channels TEXT,
    PRIMARY KEY (ip, port)
)
"""

UPSERT_SQL = """
    INSERT INTO servers (ip, port, version, proto, motd, is_modded, players_online,
                         players_max, favicon, auth, ping_ms, json, last_updated,
                         core_type, mods, forge_channels)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(ip, port) DO UPDATE SET
        version=excluded.version, proto=excluded.proto, motd=excluded.motd,
        is_modded=excluded.is_modded, players_online=excluded.players_online,
        players_max=excluded.players_max, favicon=excluded.favicon,
        auth=excluded.auth, ping_ms=excluded.ping_ms,
        json=excluded.json, last_updated=excluded.last_updated,
        core_type=excluded.core_type, mods=excluded.mods,
        forge_channels=excluded.forge_channels
"""

# 需要确保存在的列（用于旧数据库自动迁移）
_REQUIRED_COLUMNS = {
    "core_type": "TEXT",
    "mods": "TEXT",
    "forge_channels": "TEXT",
}

QUERY_COLS = ["ip", "port", "version", "proto", "motd", "is_modded",
              "players_online", "players_max", "favicon", "auth", "ping_ms",
              "last_updated", "core_type", "mods", "forge_channels"]


def get_conn(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def _migrate(conn):
    """检查并添加缺失的列（旧数据库自动升级）。"""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(servers)").fetchall()}
    for col, col_type in _REQUIRED_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE servers ADD COLUMN {col} {col_type}")


def init_db(db_path: str):
    conn = get_conn(db_path)
    conn.execute(SCHEMA)
    _migrate(conn)
    conn.commit()
    conn.close()


def upsert_server(db_path: str, rec: dict):
    conn = get_conn(db_path)
    conn.execute(UPSERT_SQL, _record_to_tuple(rec))
    conn.commit()
    conn.close()


def upsert_many(db_path: str, records: list) -> int:
    if not records:
        return 0
    conn = get_conn(db_path)
    rows = [_record_to_tuple(r) for r in records]
    conn.executemany(UPSERT_SQL, rows)
    conn.commit()
    conn.close()
    return len(rows)


def _record_to_tuple(rec: dict) -> tuple:
    mods = rec.get("mods")
    if mods is not None and not isinstance(mods, str):
        mods = json.dumps(mods, ensure_ascii=False)[:2000]
    channels = rec.get("forge_channels")
    if channels is not None and not isinstance(channels, str):
        channels = json.dumps(channels, ensure_ascii=False)[:2000]
    return (
        rec.get('ip'), rec.get('port'),
        rec.get('version'), rec.get('proto'),
        rec.get('motd'), rec.get('is_modded', 0),
        rec.get('players_online', 0), rec.get('players_max', 0),
        rec.get('favicon'), rec.get('auth', 'unknown'),
        rec.get('ping_ms'), rec.get('json'),
        datetime.now(timezone.utc).isoformat(),
        rec.get('core_type', 'unknown'),
        mods,
        channels,
    )


def _row_to_dict(row, cols):
    d = dict(zip(cols, row))
    for key in ("mods", "forge_channels"):
        val = d.get(key)
        if val and isinstance(val, str):
            try:
                d[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                d[key] = []
    return d


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def query(db_path: str, auth: str = None, modded: int = None,
          core_type: str = None, search: str = None,
          limit: int = 200, offset: int = 0) -> list:
    conn = get_conn(db_path)
    sql = "SELECT " + ", ".join(QUERY_COLS) + " FROM servers"
    conds, args = [], []
    if auth:
        conds.append("auth = ?")
        args.append(auth)
    if modded is not None:
        conds.append("is_modded = ?")
        args.append(1 if modded else 0)
    if core_type:
        conds.append("core_type = ?")
        args.append(core_type)
    if search:
        conds.append("(motd LIKE ? ESCAPE '\\' OR version LIKE ? ESCAPE '\\' OR ip LIKE ? ESCAPE '\\')")
        escaped = f"%{_escape_like(search)}%"
        args += [escaped] * 3
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY last_updated DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [_row_to_dict(r, QUERY_COLS) for r in rows]


def count(db_path: str, auth: str = None, modded: int = None,
          core_type: str = None, search: str = None) -> int:
    conn = get_conn(db_path)
    sql = "SELECT COUNT(*) FROM servers"
    conds, args = [], []
    if auth:
        conds.append("auth = ?")
        args.append(auth)
    if modded is not None:
        conds.append("is_modded = ?")
        args.append(1 if modded else 0)
    if core_type:
        conds.append("core_type = ?")
        args.append(core_type)
    if search:
        conds.append("(motd LIKE ? ESCAPE '\\' OR version LIKE ? ESCAPE '\\' OR ip LIKE ? ESCAPE '\\')")
        escaped = f"%{_escape_like(search)}%"
        args += [escaped] * 3
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    total = conn.execute(sql, args).fetchone()[0]
    conn.close()
    return total


def stats(db_path: str) -> dict:
    conn = get_conn(db_path)
    total = conn.execute("SELECT COUNT(*) FROM servers").fetchone()[0]
    by_auth = {r[0]: r[1] for r in conn.execute(
        "SELECT auth, COUNT(*) FROM servers GROUP BY auth")}
    online_servers = conn.execute(
        "SELECT COUNT(*) FROM servers WHERE players_online > 0").fetchone()[0]
    by_version = {}
    try:
        by_version = {r[0]: r[1] for r in conn.execute(
            "SELECT version, COUNT(*) FROM servers GROUP BY version ORDER BY COUNT(*) DESC LIMIT 20")}
    except Exception:
        pass
    by_core = {}
    try:
        by_core = {r[0]: r[1] for r in conn.execute(
            "SELECT core_type, COUNT(*) FROM servers WHERE core_type IS NOT NULL AND core_type != '' GROUP BY core_type ORDER BY COUNT(*) DESC")}
    except Exception:
        pass
    conn.close()
    return {
        "total": total,
        "by_auth": by_auth,
        "online_servers": online_servers,
        "by_version": by_version,
        "by_core": by_core,
    }


def default_db_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mcscanner.db')
