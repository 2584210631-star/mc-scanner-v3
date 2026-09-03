# -*- coding: utf-8 -*-
"""
异步综合扫描引擎：端口扫描 → SLP 探测 → 认证检测，流水线并行。
端口一开就立刻 SLP 探测，不用等全部端口扫完。
比同步两阶段引擎快 5-10 倍。
"""
import asyncio
import time
import threading
from typing import Optional

from scanner.async_portscan import _check_port, has_uvloop
from scanner.async_probe import async_slp_probe, async_auth_probe, has_simdjson
from storage import db


class AsyncScanEngine:
    """异步综合扫描引擎"""

    def __init__(self, db_path: str = "mcscanner.db",
                 concurrency: int = 1000,
                 slp_concurrency: int = 200,
                 timeout: float = 4.0,
                 auth_check: bool = True,
                 rate_limit: int = 0,
                 stop_event: Optional[threading.Event] = None):
        self.db_path = db_path
        self.concurrency = concurrency      # 端口扫描并发
        self.slp_concurrency = slp_concurrency  # SLP 探测并发
        self.timeout = timeout
        self.auth_check = auth_check
        self.rate_limit = rate_limit
        self.stop_event = stop_event
        self.results = []
        self.counters = {
            "total": 0, "up": 0, "cracked": 0, "online": 0,
            "whitelist": 0, "rejected": 0, "offline": 0, "error": 0,
        }
        self._lock = threading.Lock()
        self._start_time = None

    def _bump(self, key: str, n: int = 1):
        with self._lock:
            if key in self.counters:
                self.counters[key] += n

    def _print_progress(self, done: int):
        c = dict(self.counters)
        elapsed = time.time() - self._start_time if self._start_time else 0
        speed = done / elapsed if elapsed > 0 else 0
        print(f"[{done:>7}] {speed:.0f}/s | up={c['up']} cracked={c['cracked']} "
              f"online={c['online']} whitelist={c['whitelist']} "
              f"rejected={c['rejected']} offline={c['offline']} error={c['error']}")

    async def _probe_target(self, ip: str, port: int,
                            port_sem: asyncio.Semaphore,
                            slp_sem: asyncio.Semaphore,
                            save_queue: list) -> dict:
        """单目标完整探测：端口 → SLP → 认证。"""
        if self.stop_event and self.stop_event.is_set():
            return {"ip": ip, "port": port, "state": "cancelled"}

        # 阶段1：端口扫描
        async with port_sem:
            if self.rate_limit > 0:
                await asyncio.sleep(1.0 / self.rate_limit)
            port_result = await _check_port(ip, port, self.timeout, port_sem)

        self._bump("total")

        if not port_result.is_open:
            self._bump("offline")
            return {"ip": ip, "port": port, "state": "offline",
                    "error": port_result.error}

        # 阶段2：SLP 探测（端口一开就立刻探测，流水线）
        async with slp_sem:
            try:
                slp = await async_slp_probe(ip, port, self.timeout)
            except Exception as e:
                self._bump("error")
                return {"ip": ip, "port": port, "state": "error", "error": str(e)[:100]}

        if slp.get("state") != "up":
            self._bump("offline")
            return {"ip": ip, "port": port, "state": "offline",
                    "error": slp.get("error", "")}

        result = {
            "ip": ip, "port": port,
            "version": slp.get("version", ""),
            "proto": slp.get("proto", 0),
            "motd": slp.get("motd", ""),
            "ping_ms": slp.get("ping_ms"),
            "favicon": slp.get("favicon", ""),
            "core_type": slp.get("core_type", "unknown"),
            "mods": slp.get("mods", []),
            "forge_channels": slp.get("forge_channels", []),
            "players_online": slp.get("online", 0),
            "players_max": slp.get("max", 0),
            "player_list": [p.get("name", "") for p in slp.get("sample", [])],
            "state": "up",
        }
        ct = result["core_type"]
        result["is_modded"] = 1 if ct in ("forge", "fabric", "neoforge", "quilt") else 0
        result["is_plugin"] = 1 if ct in ("paper", "spigot", "bukkit", "purpur",
                                          "catserver", "arclight") else 0
        result["server_type"] = ct if ct != "unknown" else (
            "modded" if result["is_modded"] else
            ("plugin" if result["is_plugin"] else "vanilla"))
        self._bump("up")

        # 阶段3：认证检测
        if self.auth_check:
            try:
                auth = await async_auth_probe(ip, port, result.get("proto", 0),
                                              self.timeout)
                result["auth"] = auth["state"]
                result["auth_detail"] = auth.get("detail", "")
                if auth.get("detected_proto"):
                    result["proto"] = auth["detected_proto"]
                self._bump(result["auth"])
            except Exception:
                result["auth"] = "unknown"

        # 存入保存队列
        save_queue.append(result)
        if len(save_queue) >= 100:
            batch = save_queue[:]
            save_queue.clear()
            try:
                db.upsert_many(self.db_path, batch)
            except Exception:
                pass

        return result

    async def _scan_async(self, targets) -> list:
        """异步扫描主循环。"""
        db.init_db(self.db_path)
        self._start_time = time.time()
        port_sem = asyncio.Semaphore(self.concurrency)
        slp_sem = asyncio.Semaphore(self.slp_concurrency)
        save_queue = []
        tasks = []
        done = 0

        for ip, port in targets:
            if self.stop_event and self.stop_event.is_set():
                break
            tasks.append(asyncio.create_task(
                self._probe_target(ip, port, port_sem, slp_sem, save_queue)))

            # 控制任务数量，避免百万级目标一次性创建太多协程
            if len(tasks) >= 5000:
                done_batch = await asyncio.gather(*tasks)
                self.results.extend(done_batch)
                done += len(done_batch)
                tasks = []
                if done % 1000 == 0:
                    self._print_progress(done)

        if tasks:
            done_batch = await asyncio.gather(*tasks)
            self.results.extend(done_batch)
            done += len(done_batch)

        # 保存剩余
        if save_queue:
            try:
                db.upsert_many(self.db_path, save_queue)
            except Exception:
                pass

        self._print_progress(done)
        elapsed = time.time() - self._start_time
        print(f"[*] 异步扫描完成: {done} 个目标, {elapsed:.1f}s, "
              f"{done/elapsed:.0f}/s")
        return self.results

    def scan(self, targets) -> list:
        """同步入口：启动事件循环执行异步扫描。"""
        async def _run():
            return await self._scan_async(targets)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return _run()  # 返回协程，由调用方 await
        except RuntimeError:
            pass

        return asyncio.run(_run())

    def scan_with_portscan(self, targets, scan_concurrency: int = 1000,
                           scan_timeout: float = 2.5) -> list:
        """两阶段扫描（端口扫描 + SLP探测），异步版本。"""
        print(f"[*] 异步流水线扫描（并发={self.concurrency}, SLP并发={self.slp_concurrency}）")
        print(f"[*] uvloop: {'启用' if has_uvloop() else '未安装'}, "
              f"simdjson: {'启用' if has_simdjson() else '未安装'}")
        return self.scan(targets)


def run_async_scan(targets, **kwargs) -> list:
    """便捷函数：创建异步引擎并扫描。"""
    engine = AsyncScanEngine(**kwargs)
    return engine.scan(targets)
