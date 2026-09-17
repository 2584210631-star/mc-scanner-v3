# -*- coding: utf-8 -*-
"""
自动扫描警告模块。
支持多种任务类型：扫描警告、状态监控、玩家数监控、定时警告、新服务器发现、AI自动托管。
"""
import asyncio
import json
import threading
import time
from datetime import datetime
from collections import deque

from scanner.async_portscan import scan_ports_async
from scanner.async_probe import async_slp_probe


class AutoScanner:
    """自动扫描+警告调度器，支持多种任务类型"""

    # 任务类型说明
    TASK_TYPES = {
        "scan_warn": "扫描IP段+发现有人自动警告/观察",
        "monitor_status": "监控指定服务器在线/离线状态",
        "monitor_players": "监控指定服务器玩家数变化，超阈值警告",
        "scheduled_warn": "定时对指定服务器发警告",
        "discover_new": "扫描IP段发现新MC服务器，自动加入收藏",
        "ai_hijack": "发现有人的服务器自动启动AI bot进去聊天",
    }

    def __init__(self, db_path="mcscanner.db"):
        self.db_path = db_path
        self.tasks = {}  # task_id -> config
        self.running = {}  # task_id -> thread
        self.stop_events = {}  # task_id -> Event
        self.logs = {}  # task_id -> deque
        self._known_servers = {}  # task_id -> set of "ip:port" 用于发现新服务器
        self._last_status = {}  # task_id -> {"ip:port": bool} 用于状态变化检测
        self._lock = threading.Lock()
        self._seq = 0

    def _next_id(self):
        self._seq += 1
        return f"auto_{self._seq}"

    @staticmethod
    def _ts():
        return datetime.now().strftime("%H:%M:%S")

    def _log(self, task_id, msg):
        if task_id not in self.logs:
            self.logs[task_id] = deque(maxlen=500)
        self.logs[task_id].append(f"[{self._ts()}] {msg}")

    def add_task(self, config):
        """添加自动扫描任务
        config通用字段:
            task_type: 任务类型（scan_warn/monitor_status/monitor_players/scheduled_warn/discover_new/ai_hijack）
            targets: ["1.2.3.4", "1.2.3.0/24"] 或 ["1.2.3.4:25565"]
            ports: "25565" or "25565-25575"
            interval: 扫描间隔(秒)
            concurrency: 扫描并发
            timeout: 超时

        各类型特有字段:
            scan_warn: min_players, warn_enabled, warn_message, observe_enabled, observe_duration
            monitor_status: 无特有，状态变化时记录日志
            monitor_players: player_threshold, warn_enabled, warn_message, observe_enabled
            scheduled_warn: warn_message, warn_interval（每次警告间隔，默认等于interval）
            discover_new: auto_favorite（自动加入收藏）
            ai_hijack: ai_config（AI配置）, min_players
        """
        task_id = self._next_id()
        config["task_id"] = task_id
        config.setdefault("task_type", "scan_warn")
        config["created_at"] = datetime.now().isoformat()
        config["last_run"] = None
        config["run_count"] = 0
        config["total_found"] = 0
        config["total_warned"] = 0
        with self._lock:
            self.tasks[task_id] = config
            self.stop_events[task_id] = threading.Event()
            self._known_servers[task_id] = set()
            self._last_status[task_id] = {}
        ttype = config.get("task_type", "scan_warn")
        self._log(task_id, f"任务已创建 [{self.TASK_TYPES.get(ttype, ttype)}]: {config.get('targets')} 间隔={config.get('interval')}s")
        return task_id

    def remove_task(self, task_id):
        self.stop_task(task_id)
        with self._lock:
            self.tasks.pop(task_id, None)
            self.logs.pop(task_id, None)
            self._known_servers.pop(task_id, None)
            self._last_status.pop(task_id, None)

    def start_task(self, task_id):
        if task_id in self.running and self.running[task_id].is_alive():
            return False
        self.stop_events[task_id] = threading.Event()
        t = threading.Thread(target=self._run_loop, args=(task_id,), daemon=True)
        self.running[task_id] = t
        t.start()
        self._log(task_id, "任务已启动")
        return True

    def stop_task(self, task_id):
        if task_id in self.stop_events:
            self.stop_events[task_id].set()
        if task_id in self.running:
            self.running[task_id].join(timeout=5)
        self._log(task_id, "任务已停止")

    def _parse_targets(self, targets, ports_spec):
        """解析目标列表为(ip, port)元组列表。支持 ip:port 格式"""
        import ipaddress
        result = []
        ports = self._parse_ports(ports_spec)
        for target in targets:
            target = target.strip()
            if not target:
                continue
            # 支持 ip:port 格式
            if ':' in target and target.count('.') == 3:
                try:
                    ip, port_str = target.rsplit(':', 1)
                    result.append((ip.strip(), int(port_str.strip())))
                    continue
                except Exception:
                    pass
            if '/' in target:
                try:
                    network = ipaddress.ip_network(target, strict=False)
                    for ip in network.hosts():
                        for p in ports:
                            result.append((str(ip), p))
                except Exception:
                    pass
            elif '-' in target and target.count('.') == 3:
                try:
                    start, end = target.split('-')
                    start_ip = ipaddress.ip_address(start.strip())
                    end_ip = ipaddress.ip_address(end.strip())
                    current = start_ip
                    while current <= end_ip:
                        for p in ports:
                            result.append((str(current), p))
                        current = ipaddress.ip_address(int(current) + 1)
                except Exception:
                    pass
            else:
                for p in ports:
                    result.append((target, p))
        return result

    @staticmethod
    def _parse_ports(ports_spec):
        if not ports_spec:
            return [25565]
        if isinstance(ports_spec, int):
            return [ports_spec]
        result = []
        for part in str(ports_spec).split(','):
            part = part.strip()
            if '-' in part:
                try:
                    s, e = part.split('-')
                    result.extend(range(int(s), int(e) + 1))
                except Exception:
                    pass
            else:
                try:
                    result.append(int(part))
                except Exception:
                    pass
        return sorted(set(result)) if result else [25565]

    def _run_loop(self, task_id):
        config = self.tasks[task_id]
        stop_event = self.stop_events[task_id]
        interval = int(config.get("interval", 300))

        while not stop_event.is_set():
            try:
                ttype = config.get("task_type", "scan_warn")
                if ttype == "scan_warn":
                    self._run_scan_warn(task_id, config)
                elif ttype == "monitor_status":
                    self._run_monitor_status(task_id, config)
                elif ttype == "monitor_players":
                    self._run_monitor_players(task_id, config)
                elif ttype == "scheduled_warn":
                    self._run_scheduled_warn(task_id, config)
                elif ttype == "discover_new":
                    self._run_discover_new(task_id, config)
                elif ttype == "ai_hijack":
                    self._run_ai_hijack(task_id, config)
                else:
                    self._log(task_id, f"未知任务类型: {ttype}")
            except Exception as e:
                self._log(task_id, f"执行出错: {e}")
            config["last_run"] = datetime.now().isoformat()
            config["run_count"] += 1
            # 等待间隔，可被中断
            for _ in range(interval):
                if stop_event.is_set():
                    break
                time.sleep(1)

    def _probe_servers(self, targets, task_id, concurrency=200, timeout=2.0):
        """通用：端口扫描+SLP探测，返回MC服务器列表"""
        if not targets:
            self._log(task_id, "无有效目标")
            return []

        self._log(task_id, f"开始扫描: {len(targets)} 个目标")
        stop_event = asyncio.Event()

        async def scan():
            results = await scan_ports_async(
                targets, concurrency=concurrency, timeout=timeout,
                stop_event=stop_event,
            )
            open_ports = [(r.ip, r.port) for r in results if r.is_open]
            self._log(task_id, f"端口扫描完成: {len(open_ports)} 个开放")

            mc_servers = []
            sem = asyncio.Semaphore(50)

            async def probe(ip, port):
                async with sem:
                    try:
                        info = await async_slp_probe(ip, port, timeout=3)
                        if info and info.get('state') == 'up':
                            ct = info.get('core_type', 'unknown')
                            return {
                                'ip': ip, 'port': port,
                                'state': 'up',
                                'version': info.get('version', '?'),
                                'proto': info.get('proto', 0),
                                'motd': str(info.get('motd', ''))[:200],
                                'players_online': info.get('online', 0),
                                'players_max': info.get('max', 0),
                                'player_list': [p.get('name', '') for p in info.get('sample', [])],
                                'core_type': ct,
                                'is_modded': 1 if ct in ('forge', 'fabric', 'neoforge', 'quilt') else 0,
                                'favicon': info.get('favicon', ''),
                                'ping_ms': info.get('ping_ms', 0),
                                'auth': 'unknown',
                            }
                    except Exception:
                        pass
                return None

            tasks = [probe(ip, port) for ip, port in open_ports]
            for r in await asyncio.gather(*tasks):
                if r:
                    mc_servers.append(r)
            return mc_servers

        return asyncio.run(scan())

    def _run_scan_warn(self, task_id, config):
        """类型1: 扫描IP段+发现有人自动警告/观察"""
        targets = self._parse_targets(config.get("targets", []), config.get("ports", "25565"))
        mc_servers = self._probe_servers(targets, task_id,
                                         concurrency=int(config.get("concurrency", 200)),
                                         timeout=float(config.get("timeout", 2.0)))
        config["total_found"] += len(mc_servers)
        self._log(task_id, f"SLP探测完成: {len(mc_servers)} 个MC服务器")

        min_players = int(config.get("min_players", 1))
        alive = [s for s in mc_servers if s['players_online'] >= min_players]
        self._log(task_id, f"有人服务器: {len(alive)} 个 (>= {min_players}人)")

        if config.get("warn_enabled") and alive:
            warned = self._warn_servers(alive, config.get("warn_message", "服务器安全提示"))
            config["total_warned"] += warned
            self._log(task_id, f"已警告 {warned} 个服务器")

        if config.get("observe_enabled") and alive:
            self._observe_servers(alive, config.get("observe_duration", 60))
            self._log(task_id, f"已对 {len(alive)} 个服务器启动观察者")

    def _run_monitor_status(self, task_id, config):
        """类型2: 监控指定服务器在线/离线状态，变化时记录"""
        targets = self._parse_targets(config.get("targets", []), config.get("ports", "25565"))
        mc_servers = self._probe_servers(targets, task_id, concurrency=50, timeout=3.0)
        online_set = {f"{s['ip']}:{s['port']}" for s in mc_servers}
        last = self._last_status.get(task_id, {})

        for key in online_set:
            if key in last and not last[key]:
                self._log(task_id, f"🔴→🟢 服务器上线: {key}")
            elif key not in last:
                self._log(task_id, f"🟢 首次检测到在线: {key}")
            last[key] = True

        for key, was_online in last.items():
            if key not in online_set and was_online:
                self._log(task_id, f"🟢→🔴 服务器离线: {key}")
            last[key] = key in online_set

        self._last_status[task_id] = last
        self._log(task_id, f"状态监控完成: 在线 {len(online_set)}/{len(targets)}")

    def _run_monitor_players(self, task_id, config):
        """类型3: 监控指定服务器玩家数，超过阈值时警告/观察"""
        targets = self._parse_targets(config.get("targets", []), config.get("ports", "25565"))
        mc_servers = self._probe_servers(targets, task_id, concurrency=50, timeout=3.0)
        threshold = int(config.get("player_threshold", 5))
        triggered = [s for s in mc_servers if s['players_online'] >= threshold]

        self._log(task_id, f"玩家监控: {len(mc_servers)} 个在线, {len(triggered)} 个达到阈值(>={threshold}人)")
        for s in triggered:
            self._log(task_id, f"  ⚠️ {s['ip']}:{s['port']} 玩家数={s['players_online']} 版本={s['version']}")

        if config.get("warn_enabled") and triggered:
            warned = self._warn_servers(triggered, config.get("warn_message", "服务器安全提示"))
            config["total_warned"] += warned
            self._log(task_id, f"已警告 {warned} 个服务器")

        if config.get("observe_enabled") and triggered:
            self._observe_servers(triggered, config.get("observe_duration", 60))
            self._log(task_id, f"已对 {len(triggered)} 个服务器启动观察者")

    def _run_scheduled_warn(self, task_id, config):
        """类型4: 定时对指定服务器发警告（不扫描，直接连）"""
        targets = self._parse_targets(config.get("targets", []), config.get("ports", "25565"))
        message = config.get("warn_message", "服务器安全提示")
        warned = self._warn_servers(
            [{'ip': ip, 'port': p, 'proto': None} for ip, p in targets],
            message
        )
        config["total_warned"] += warned
        self._log(task_id, f"定时警告完成: 尝试 {len(targets)} 个, 成功 {warned} 个")

    def _run_discover_new(self, task_id, config):
        """类型5: 扫描IP段，发现新MC服务器（之前没扫到的），自动加入收藏"""
        targets = self._parse_targets(config.get("targets", []), config.get("ports", "25565"))
        mc_servers = self._probe_servers(targets, task_id,
                                         concurrency=int(config.get("concurrency", 200)),
                                         timeout=float(config.get("timeout", 2.0)))
        known = self._known_servers.get(task_id, set())
        new_servers = []
        for s in mc_servers:
            key = f"{s['ip']}:{s['port']}"
            if key not in known:
                new_servers.append(s)
                known.add(key)
        self._known_servers[task_id] = known

        config["total_found"] += len(mc_servers)
        self._log(task_id, f"发现 {len(new_servers)} 个新服务器 (总计 {len(known)} 个已知)")
        for s in new_servers:
            self._log(task_id, f"  🆕 {s['ip']}:{s['port']} {s['version']} 玩家={s['players_online']} MOTD={s['motd']}")

        if config.get("auto_favorite") and new_servers:
            self._favorite_servers(new_servers)
            self._log(task_id, f"已自动加入收藏 {len(new_servers)} 个")

    def _run_ai_hijack(self, task_id, config):
        """类型6: 发现有人的服务器自动启动AI bot进去聊天"""
        targets = self._parse_targets(config.get("targets", []), config.get("ports", "25565"))
        mc_servers = self._probe_servers(targets, task_id,
                                         concurrency=int(config.get("concurrency", 200)),
                                         timeout=float(config.get("timeout", 2.0)))
        min_players = int(config.get("min_players", 1))
        alive = [s for s in mc_servers if s['players_online'] >= min_players]
        self._log(task_id, f"AI托管扫描: {len(alive)} 个有人服务器 (>= {min_players}人)")

        if alive:
            ai_cfg = config.get("ai_config", {})
            for s in alive[:3]:  # 最多同时启动3个AI，避免资源耗尽
                self._start_ai_bot(s, ai_cfg)
                self._log(task_id, f"  🤖 已启动AI托管: {s['ip']}:{s['port']}")

    def _warn_servers(self, servers, message):
        """对服务器列表发警告"""
        from core.bot import MCBot
        warned = 0
        for s in servers:
            try:
                bot = MCBot(host=s['ip'], port=s['port'],
                            username="SecurityBot", timeout=15,
                            protocol_version=s.get('proto'))
                bot.connect()
                if bot.state == "play":
                    bot.send_chat(message)
                    time.sleep(1)
                    bot.close()
                    warned += 1
            except Exception:
                pass
        return warned

    def _observe_servers(self, servers, duration):
        """对服务器列表挂观察者"""
        from core.bot import MCBot
        for s in servers:
            try:
                bot = MCBot(host=s['ip'], port=s['port'],
                            username="Observer", timeout=15,
                            protocol_version=s.get('proto'))
                bot.connect()
                def _hold(b, dur):
                    start = time.time()
                    while time.time() - start < dur and getattr(b, 'connected', True):
                        time.sleep(1)
                    try:
                        b.close()
                    except Exception:
                        pass
                t = threading.Thread(target=_hold, args=(bot, duration), daemon=True)
                t.start()
            except Exception:
                pass

    def _favorite_servers(self, servers):
        """自动加入收藏（写入数据库）"""
        try:
            from storage.db import upsert_many
            records = []
            for s in servers:
                records.append({
                    'ip': s['ip'], 'port': s['port'],
                    'version': s['version'], 'players': s['players_online'],
                    'max_players': s['max'], 'motd': s['motd'],
                    'protocol': s.get('proto', 0),
                })
            upsert_many(records)
        except Exception as e:
            pass

    def _start_ai_bot(self, server, ai_config):
        """启动AI托管bot"""
        try:
            from core.ai_bot import AIBotSession
            bot = AIBotSession(
                host=server['ip'], port=server['port'],
                username="AIBot", timeout=15,
                protocol_version=server.get('proto'),
                ai_config=ai_config,
            )
            bot.session_id = f"auto_{server['ip']}_{server['port']}"
            bot.start()
        except Exception as e:
            pass

    def list_tasks(self):
        with self._lock:
            return [
                {
                    "task_id": tid,
                    "task_type": cfg.get("task_type", "scan_warn"),
                    "task_type_name": self.TASK_TYPES.get(cfg.get("task_type", "scan_warn"), cfg.get("task_type")),
                    "targets": cfg.get("targets", []),
                    "ports": cfg.get("ports", "25565"),
                    "interval": cfg.get("interval", 300),
                    "min_players": cfg.get("min_players", 1),
                    "warn_enabled": cfg.get("warn_enabled", True),
                    "observe_enabled": cfg.get("observe_enabled", False),
                    "status": "running" if tid in self.running and self.running[tid].is_alive() else "stopped",
                    "last_run": cfg.get("last_run"),
                    "run_count": cfg.get("run_count", 0),
                    "total_found": cfg.get("total_found", 0),
                    "total_warned": cfg.get("total_warned", 0),
                }
                for tid, cfg in self.tasks.items()
            ]

    def get_logs(self, task_id, limit=100):
        if task_id in self.logs:
            return list(self.logs[task_id])[-limit:]
        return []


# 全局单例
auto_scanner = AutoScanner()
