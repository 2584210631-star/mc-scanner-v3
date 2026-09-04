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

from core.probe import slp_probe, auth_probe, active_fingerprint
from core.bot import join_and_warn
from storage import db
from .portscan import scan_ports, get_open_ports
from .banner import parse_banner, extract_records


class ScanEngine:
    """综合扫描引擎"""

    def __init__(self, db_path: str = "mcscanner.db", workers: int = 32,
                 timeout: float = 4.0, auth_check: bool = True, rate_limit: int = 0,
                 bot_workers: int = 10, bot_timeout: float = 12.0, stop_event=None,
                 rescan_enabled: bool = False, duplicate_detection: bool = False,
                 discord_webhook: str = ""):
        self.db_path = db_path
        self.workers = workers
        self.timeout = timeout
        self.auth_check = auth_check
        self.rate_limit = rate_limit
        self.bot_workers = bot_workers
        self.bot_timeout = bot_timeout
        self.stop_event = stop_event
        # v3.2.1 新增特性
        self.rescan_enabled = rescan_enabled
        self.duplicate_detection = duplicate_detection
        self.discord_webhook = discord_webhook
        self._rescheduler = None
        self._dup_detector = None
        self._discord = None
        self._lock = threading.Lock()
        self._last_probe = 0.0
        self._tokens = 0.0
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
                               ("version", "proto", "motd", "ping_ms", "favicon",
                                "core_type", "mods", "forge_channels", "fingerprint")})
                result["players_online"] = up.get("online", 0)
                result["players_max"] = up.get("max", 0)
                result["player_list"] = [p.get("name", "") for p in up.get("sample", [])]
                # 模组服/插件服识别：优先用 core_type，回退到关键词
                ct = result.get("core_type", "unknown")
                result["is_modded"] = 1 if ct in ("forge", "fabric", "neoforge", "quilt") else 0
                result["is_plugin"] = 1 if ct in ("paper", "spigot", "bukkit", "purpur", "catserver", "arclight") else 0
                result["server_type"] = ct if ct != "unknown" else ("modded" if result["is_modded"] else ("plugin" if result["is_plugin"] else "vanilla"))
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
            # v3.3.2: 主动协议指纹（malformed login 探测服务端软件）
            try:
                proto = result.get("proto") or 0
                af = active_fingerprint(ip, port, proto, timeout=self.timeout)
                fp = result.get("fingerprint") or {}
                fp["active_software"] = af.get("software", "unknown")
                fp["active_confidence"] = af.get("confidence", 0)
                fp["active_raw_error"] = af.get("raw_error", "")
                # 主动指纹置信度更高时覆盖被动推断
                if af.get("confidence", 0) > fp.get("confidence", 0):
                    fp["likely_software"] = af.get("software", fp.get("likely_software"))
                    fp["confidence"] = af.get("confidence", fp.get("confidence"))
                    fp["fingerprint_source"] = "active"
                else:
                    fp["fingerprint_source"] = fp.get("fingerprint_source", "passive")
                result["fingerprint"] = fp
            except Exception:
                pass
            # v3.2.1: 探测后钩子（玩家历史/重扫/重复检测/Discord通知）
            self._post_probe_hooks(result)
        except Exception as e:
            result["state"] = "error"
            result["error"] = str(e)
            self._bump("error")
        return result

    def _run_batch(self, targets, fn, save_callback=None, save_every=50):
        """分批提交任务到线程池，避免大网段一次性提交导致OOM。
        fn: 接收 (ip, port) 返回结果的函数
        save_callback: 每save_every个结果调用一次，接收结果列表
        """
        BATCH_SIZE = max(self.workers * 4, 200)
        results = []
        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as ex:
            futures = {}
            target_iter = iter(targets)
            # 初始填充一批
            for ip, port in target_iter:
                if len(futures) >= BATCH_SIZE:
                    break
                futures[ex.submit(fn, ip, port)] = (ip, port)
            while futures:
                if self.stop_event and self.stop_event.is_set():
                    for f in futures:
                        f.cancel()
                    break
                done_set, _ = concurrent.futures.wait(
                    futures, return_when=concurrent.futures.FIRST_COMPLETED)
                for fut in done_set:
                    ip, port = futures.pop(fut)
                    try:
                        r = fut.result()
                    except Exception as e:
                        r = {"ip": ip, "port": port, "state": "error", "error": str(e)}
                    results.append(r)
                    done += 1
                    self._bump("total")
                    if save_callback and done % save_every == 0:
                        save_callback(results[-save_every:])
                        self._print_progress(done)
                # 补充新任务
                for ip, port in target_iter:
                    if len(futures) >= BATCH_SIZE:
                        break
                    futures[ex.submit(fn, ip, port)] = (ip, port)
        return results, done

    def scan_targets(self, targets, save_every: int = 50) -> list:
        """批量扫描目标（分批提交，大网段不OOM）"""
        db.init_db(self.db_path)
        def _save(batch):
            db.upsert_many(self.db_path, batch)
        results, _ = self._run_batch(targets, self.probe_one, _save, save_every)
        if results:
            db.upsert_many(self.db_path, results)
        self.results = results
        return results

    def probe_list(self, targets: list) -> list:
        """批量探测 (ip, port) 列表，返回结果（不存数据库，分批提交不OOM）"""
        results, _ = self._run_batch(targets, self.probe_one)
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
                           if r.get("auth") == "cracked"]

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
                if self.stop_event and self.stop_event.is_set():
                    break
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

    # ===== v3.2.1 新增：探测后钩子 =====

    def _get_rescheduler(self):
        """惰性初始化重扫调度器。"""
        if self._rescheduler is None:
            from scanner.rescanner import RescanScheduler
            self._rescheduler = RescanScheduler(self.db_path, enabled=self.rescan_enabled)
        return self._rescheduler

    def _get_dup_detector(self):
        """惰性初始化重复检测器。"""
        if self._dup_detector is None:
            from scanner.duplicate import DuplicateDetector
            self._dup_detector = DuplicateDetector()
        return self._dup_detector

    def _get_discord(self):
        """惰性初始化 Discord 通知器。"""
        if self._discord is None:
            from notify.discord import DiscordNotifier
            self._discord = DiscordNotifier(self.discord_webhook)
        return self._discord

    def _post_probe_hooks(self, result: dict):
        """
        探测成功后钩子：玩家历史、重扫队列、重复检测、Discord通知。
        所有钩子都在 try/except 中，不影响主流程。
        """
        if result.get("state") != "up":
            return
        try:
            # 1. 玩家历史 + 重扫队列
            if self.rescan_enabled:
                self._get_rescheduler().update(result)
            elif result.get("player_list"):
                # 即使不开启重扫，也记录玩家历史
                from storage import player_history as ph
                ph.update_players(self.db_path, result["ip"], result["port"], result["player_list"])
        except Exception:
            pass
        try:
            # 2. 重复服务器检测
            if self.duplicate_detection:
                self._get_dup_detector().add(result)
        except Exception:
            pass
        try:
            # 3. Discord 通知
            if self.discord_webhook:
                d = self._get_discord()
                d.notify_new_server(result)
                if result.get("auth") == "cracked":
                    d.notify_cracked_server(result)
        except Exception:
            pass

    def rescan_due(self, limit: int = 50) -> list:
        """
        执行到期的重扫任务（v3.2.1 新增）。
        返回重扫结果列表。
        """
        if not self.rescan_enabled:
            return []
        scheduler = self._get_rescheduler()
        due = scheduler.get_due(limit=limit)
        if not due:
            return []
        results = []
        for item in due:
            try:
                r = self.probe_one(item["ip"], item["port"])
                results.append(r)
            except Exception:
                continue
        return results

    def get_duplicates(self) -> list:
        """获取检测到的重复服务器组（v3.2.1 新增）。"""
        if self._dup_detector:
            return self._dup_detector.get_duplicates()
        return []


def _looks_modded(version: str) -> bool:
    """判断是否为模组服（Forge/Fabric/NeoForge/Quilt），不包含插件服"""
    v = (version or "").lower()
    return any(kw in v for kw in ("forge", "fabric", "neoforge", "quilt", "fml", "modloader"))


def _looks_plugin(version: str) -> bool:
    """判断是否为插件服（Paper/Spigot/Bukkit/Purpur）"""
    v = (version or "").lower()
    return any(kw in v for kw in ("paper", "spigot", "bukkit", "purpur", "catserver", "arclight"))
