# -*- coding: utf-8 -*-
"""
综合扫描引擎：端口扫描 → SLP 探测 → 认证检测 → 存储。
融合 V1 的功能完整性和 V2 的两阶段分离架构。
"""
import concurrent.futures
import json
import threading
import time
from typing import Optional

from core.probe import slp_probe, auth_probe
from core.bot import join_and_warn
from storage import db
from .portscan import scan_ports, get_open_ports
from .banner import parse_banner, extract_records


class ScanEngine:
    """综合扫描引擎"""

    def __init__(self, db_path: str = "mcscanner.db", workers: int = 32,
                 timeout: float = 4.0, auth_check: bool = True, rate_limit: int = 0,
                 bot_workers: int = 10, bot_timeout: float = 12.0):
        self.db_path = db_path
        self.workers = workers
        self.timeout = timeout
        self.auth_check = auth_check
        self.rate_limit = rate_limit
        self.bot_workers = bot_workers
        self.bot_timeout = bot_timeout
        self._lock = threading.Lock()
        self._last_probe = 0.0
        self.counters = {
            "total": 0, "up": 0, "cracked": 0, "online": 0,
            "whitelist": 0, "rejected": 0, "offline": 0, "error": 0,
            "messages_sent": 0,
        }
        self.results = []

    def _throttle(self):
        """限速"""
        if self.rate_limit <= 0:
            return
        with self._lock:
            now = time.time()
            wait = (1.0 / self.rate_limit) - (now - self._last_probe)
            if wait > 0:
                time.sleep(wait)
            self._last_probe = time.time()

    def _bump(self, key: str, n: int = 1):
        with self._lock:
            if key in self.counters:
                self.counters[key] += n

    def probe_one(self, ip: str, port: int) -> dict:
        """单目标探测：SLP + 认证检测"""
        self._throttle()
        result = {"ip": ip, "port": port, "auth": "error", "error": "", "state": "unknown"}
        try:
            up = slp_probe(ip, port, self.timeout)
            if up.get("state") == "up":
                result.update({k: up.get(k) for k in
                               ("version", "proto", "motd", "ping_ms", "favicon")})
                result["players_online"] = up.get("online", 0)
                result["players_max"] = up.get("max", 0)
                result["is_modded"] = 1 if _looks_modded(up.get("version", "")) else 0
                result["state"] = "up"
                self._bump("up")
            else:
                result["state"] = "offline"
                result["error"] = up.get("error", "")
                self._bump("offline")
                return result

            if self.auth_check:
                proto = result.get("proto") or 0
                auth = auth_probe(ip, port, proto, timeout=self.timeout)
                result["auth"] = auth["state"]
                result["auth_detail"] = auth.get("detail", "")
                if auth.get("detected_proto"):
                    result["proto"] = auth["detected_proto"]
                self._bump(result["auth"])
            else:
                result["auth"] = "unknown"
        except Exception as e:
            result["state"] = "error"
            result["error"] = str(e)
            self._bump("error")
        return result

    def scan_targets(self, targets, save_every: int = 50) -> list:
        """批量扫描目标（惰性生成器）"""
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as ex:
            futures = {ex.submit(self.probe_one, ip, port): (ip, port)
                       for ip, port in targets}
            done = 0
            for fut in concurrent.futures.as_completed(futures):
                try:
                    r = fut.result()
                except Exception as e:
                    ip, port = futures[fut]
                    r = {"ip": ip, "port": port, "state": "error", "error": str(e)}
                results.append(r)
                done += 1
                self._bump("total")
                if done % save_every == 0:
                    db.upsert_many(self.db_path, results[-save_every:])
                    self._print_progress(done)
        if results:
            db.upsert_many(self.db_path, results)
        self.results = results
        return results

    def scan_with_portscan(self, targets, scan_threads: int = 200,
                            scan_timeout: float = 2.5) -> list:
        """两阶段扫描：先端口扫描，再对开放端口做 SLP+认证检测"""
        print(f"[*] 阶段1: 端口扫描（线程={scan_threads}, 超时={scan_timeout}s）")
        port_results = scan_ports(targets, max_workers=scan_threads,
                                   timeout=scan_timeout, show_progress=True,
                                   rate=self.rate_limit)
        open_ports = get_open_ports(port_results)
        print(f"[*] 阶段1完成，开放 {len(open_ports)} 个端口")
        if not open_ports:
            return []
        print(f"[*] 阶段2: SLP探测 + 认证检测（{len(open_ports)} 个目标）")
        return self.scan_targets(iter(open_ports))

    def warn_targets(self, targets, username: str = "SecurityBot",
                     messages: list = None, message_delay: float = 0.8,
                     authme_password: str = None) -> list:
        """
        完整警告流程：扫描 → 对离线服登录发警告。
        保留 V1 的 warn 功能。
        """
        if messages is None:
            from core.bot import DEFAULT_WARNING_MESSAGES
            messages = DEFAULT_WARNING_MESSAGES

        # 先扫描发现服务器
        scan_results = self.scan_with_portscan(targets)
        offline_servers = [(r["ip"], r["port"]) for r in scan_results
                           if r.get("auth") == "cracked" or r.get("state") == "up"]

        print(f"\n[*] 发现 {len(offline_servers)} 个可警告服务器，开始发送警告...")

        # 多线程发警告
        warn_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.bot_workers) as ex:
            futures = {}
            for ip, port in offline_servers:
                fut = ex.submit(join_and_warn, ip, port, username, messages,
                                self.bot_timeout, message_delay, None, authme_password)
                futures[fut] = (ip, port)

            done = 0
            for fut in concurrent.futures.as_completed(futures):
                try:
                    r = fut.result()
                except Exception as e:
                    ip, port = futures[fut]
                    from core.bot import BotResult
                    r = BotResult(ip=ip, port=port, error=str(e))
                warn_results.append(r)
                done += 1
                if r.messages_sent > 0:
                    self._bump("messages_sent", r.messages_sent)
                if done % 10 == 0:
                    print(f"[*] 警告进度: {done}/{len(offline_servers)} "
                          f"(已发送 {self.counters['messages_sent']} 条消息)")

        # 更新数据库
        records = []
        for r in warn_results:
            records.append({
                "ip": r.ip, "port": r.port,
                "version": r.version_name, "proto": r.protocol_version,
                "motd": r.motd[:200], "is_modded": 0,
                "players_online": r.players_online, "players_max": r.players_max,
                "auth": r.auth_mode, "ping_ms": None,
                "json": json.dumps({"messages_sent": r.messages_sent,
                                     "authme_used": r.authme_used,
                                     "error": r.error}, ensure_ascii=False)[:2000],
            })
        if records:
            db.upsert_many(self.db_path, records)

        return warn_results

    def import_masscan(self, ndjson_path: str, then_auth: bool = True) -> list:
        """导入 masscan 结果，先 banner 快速入库，再认证检测"""
        db.init_db(self.db_path)
        print(f"[*] 导入 masscan banner: {ndjson_path}")
        pending = []
        total = 0
        for ip, port, banner in extract_records(ndjson_path):
            p = parse_banner(banner)
            if not p:
                p = {"version": "", "proto": 0, "motd": "", "online": 0,
                     "max": 0, "sample": [], "favicon": "", "is_modded": 0}
            p["ip"], p["port"] = ip, port
            p["auth"] = "unknown"
            p["players_online"] = p.pop("online", 0)
            p["players_max"] = p.pop("max", 0)
            pending.append(p)
            total += 1
            if len(pending) >= 500:
                db.upsert_many(self.db_path, pending)
                pending = []
        if pending:
            db.upsert_many(self.db_path, pending)
        print(f"[*] banner 导入完成，共 {total} 条")

        if then_auth:
            all_rows = db.query(self.db_path, limit=100000)
            targets = [(r["ip"], r["port"]) for r in all_rows]
            print(f"[*] 对 {len(targets)} 个已发现服务器做认证检测...")
            self.scan_targets(iter(targets))
        return self.results

    def _print_progress(self, done: int):
        c = dict(self.counters)
        print(f"[{done:>6}] up={c['up']} cracked={c['cracked']} "
              f"online={c['online']} whitelist={c['whitelist']} "
              f"rejected={c['rejected']} offline={c['offline']} error={c['error']}")


def _looks_modded(version: str) -> bool:
    v = (version or "").lower()
    return any(kw in v for kw in ("forge", "fabric", "mod", "paper", "spigot",
                                   "bukkit", "purpur", "fml"))
