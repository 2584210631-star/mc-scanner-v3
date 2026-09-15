# -*- coding: utf-8 -*-
"""
自动扫描警告模块。
定时扫描指定IP段/端口，发现有人的服务器自动发警告/挂观察者。
"""
import asyncio
import json
import threading
import time
from datetime import datetime

from scanner.async_portscan import scan_ports_async
from scanner.async_probe import async_slp_probe


class AutoScanner:
    """自动扫描+警告调度器"""

    def __init__(self, db_path="mcscanner.db"):
        self.db_path = db_path
        self.tasks = {}  # task_id -> config
        self.running = {}  # task_id -> thread
        self.stop_events = {}  # task_id -> Event
        self.logs = {}  # task_id -> deque
        self._lock = threading.Lock()
        self._seq = 0

    def _next_id(self):
        self._seq += 1
        return f"auto_{self._seq}"

    @staticmethod
    def _ts():
        return datetime.now().strftime("%H:%M:%S")

    def _log(self, task_id, msg):
        from collections import deque
        if task_id not in self.logs:
            self.logs[task_id] = deque(maxlen=500)
        self.logs[task_id].append(f"[{self._ts()}] {msg}")

    def add_task(self, config):
        """添加自动扫描任务
        config: {
            targets: ["1.2.3.4", "1.2.3.0/24"],  # 扫描目标
            ports: "25565" or "25565-25575",     # 端口
            interval: 300,                        # 扫描间隔(秒)
            min_players: 1,                       # 最少玩家数才警告
            warn_enabled: True,                   # 是否自动警告
            warn_message: "服务器安全提示...",     # 警告内容
            observe_enabled: False,               # 是否自动挂观察者
            observe_duration: 60,                 # 观察时长(秒)
            concurrency: 200,                     # 扫描并发
            timeout: 2.0,                         # 超时
        }
        """
        task_id = self._next_id()
        config["task_id"] = task_id
        config["created_at"] = datetime.now().isoformat()
        config["last_run"] = None
        config["run_count"] = 0
        config["total_found"] = 0
        config["total_warned"] = 0
        with self._lock:
            self.tasks[task_id] = config
            self.stop_events[task_id] = threading.Event()
        self._log(task_id, f"任务已创建: {config.get('targets')} 端口={config.get('ports')} 间隔={config.get('interval')}s")
        return task_id

    def remove_task(self, task_id):
        self.stop_task(task_id)
        with self._lock:
            self.tasks.pop(task_id, None)
            self.logs.pop(task_id, None)

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

    def _parse_targets(self, targets):
        """解析目标列表为(ip, port)元组列表"""
        import ipaddress
        result = []
        ports = self._parse_ports(self.tasks.get(self._current_task_id, {}).get("ports", "25565"))
        for target in targets:
            target = target.strip()
            if not target:
                continue
            if '/' in target:
                # CIDR
                try:
                    network = ipaddress.ip_network(target, strict=False)
                    for ip in network.hosts():
                        for p in ports:
                            result.append((str(ip), p))
                except Exception:
                    pass
            elif '-' in target and target.count('.') == 3:
                # IP范围 1.2.3.4-1.2.3.10
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
                # 单个IP或域名
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
        self._current_task_id = task_id
        config = self.tasks[task_id]
        stop_event = self.stop_events[task_id]
        interval = int(config.get("interval", 300))

        while not stop_event.is_set():
            try:
                self._run_scan(task_id, config)
            except Exception as e:
                self._log(task_id, f"扫描出错: {e}")
            config["last_run"] = datetime.now().isoformat()
            config["run_count"] += 1
            # 等待间隔，可被中断
            for _ in range(interval):
                if stop_event.is_set():
                    break
                time.sleep(1)

    def _run_scan(self, task_id, config):
        """执行一次扫描+警告"""
        import asyncio
        targets = self._parse_targets(config.get("targets", []))
        if not targets:
            self._log(task_id, "无有效目标")
            return

        self._log(task_id, f"开始扫描: {len(targets)} 个目标")
        stop_event = asyncio.Event()

        async def scan():
            results = await scan_ports_async(
                targets,
                concurrency=int(config.get("concurrency", 200)),
                timeout=float(config.get("timeout", 2.0)),
                stop_event=stop_event,
            )
            open_ports = [(r.ip, r.port) for r in results if r.is_open]
            self._log(task_id, f"端口扫描完成: {len(open_ports)} 个开放")

            # SLP探测
            mc_servers = []
            sem = asyncio.Semaphore(50)

            async def probe(ip, port):
                async with sem:
                    try:
                        info = await async_slp_probe(ip, port, timeout=3)
                        if info and info.get('state') == 'up':
                            pl = info.get('players', {})
                            online = pl.get('online', 0) if isinstance(pl, dict) else 0
                            return {
                                'ip': ip, 'port': port,
                                'version': info.get('version', {}).get('name', '?'),
                                'players': online,
                                'max': pl.get('max', 0) if isinstance(pl, dict) else 0,
                                'motd': str(info.get('description', ''))[:50],
                                'proto': info.get('protocol', {}).get('version', 0) if isinstance(info.get('protocol'), dict) else info.get('protocol', 0),
                            }
                    except Exception:
                        pass
                return None

            tasks = [probe(ip, port) for ip, port in open_ports]
            for r in await asyncio.gather(*tasks):
                if r:
                    mc_servers.append(r)
            return mc_servers

        mc_servers = asyncio.run(scan())
        config["total_found"] += len(mc_servers)
        self._log(task_id, f"SLP探测完成: {len(mc_servers)} 个MC服务器")

        # 筛选有人的服务器
        min_players = int(config.get("min_players", 1))
        alive = [s for s in mc_servers if s['players'] >= min_players]
        self._log(task_id, f"有人服务器: {len(alive)} 个 (>= {min_players}人)")

        # 自动警告
        if config.get("warn_enabled") and alive:
            warned = self._warn_servers(alive, config.get("warn_message", "服务器安全提示"))
            config["total_warned"] += warned
            self._log(task_id, f"已警告 {warned} 个服务器")

        # 自动挂观察者
        if config.get("observe_enabled") and alive:
            self._observe_servers(alive, config.get("observe_duration", 60))
            self._log(task_id, f"已对 {len(alive)} 个服务器启动观察者")

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
                    bot.disconnect()
                    warned += 1
            except Exception:
                pass
        return warned

    def _observe_servers(self, servers, duration):
        """对服务器列表挂观察者（简化版，只连接不回调）"""
        from core.bot import MCBot
        for s in servers:
            try:
                bot = MCBot(host=s['ip'], port=s['port'],
                            username="Observer", timeout=15,
                            protocol_version=s.get('proto'))
                bot.connect()
                # 后台线程保持连接
                def _hold(b, dur):
                    start = time.time()
                    while time.time() - start < dur and getattr(b, 'connected', True):
                        time.sleep(1)
                    try:
                        b.disconnect()
                    except Exception:
                        pass
                t = threading.Thread(target=_hold, args=(bot, duration), daemon=True)
                t.start()
            except Exception:
                pass

    def list_tasks(self):
        with self._lock:
            return [
                {
                    "task_id": tid,
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
