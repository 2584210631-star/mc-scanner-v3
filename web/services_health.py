# -*- coding: utf-8 -*-
"""Health monitor loop."""
import os, json, time, sqlite3
from datetime import datetime, timezone
import config
from core.notifier import _html_escape
try:
    from web import state
except ImportError:
    import state  # type: ignore
health_monitor = state.health_monitor
scan_lock = state.scan_lock

def _log(msg):
    state.log_scan(msg)


async def _probe_all(hosts, timeout=4.0, concurrency=3, ip_gap=4.5):
    """温和并发探测：限制总并发 + 同一IP强制节流。

    Minecraft 服务器默认 connection-throttle=4000ms（同一IP 4秒内限一次连接），
    同IP不同端口连续探测会被限速甚至被防火墙拉黑。ip_gap 默认 4.5s 留有余量。
    返回 [(ip, port, result|None)]。
    """
    import asyncio
    from scanner.async_probe import async_slp_probe
    sem = asyncio.Semaphore(max(1, concurrency))
    last_hit = {}  # ip -> 上次探测时刻（同一事件循环内访问，无并发竞争）

    async def _one(ip, port):
        async with sem:
            if ip_gap > 0:
                while True:
                    now = asyncio.get_event_loop().time()
                    wait = last_hit.get(ip, 0.0) + ip_gap - now
                    if wait <= 0:
                        last_hit[ip] = now
                        break
                    await asyncio.sleep(wait)
            try:
                return (ip, port, await async_slp_probe(ip, port, timeout=timeout))
            except Exception:
                return (ip, port, None)

    return await asyncio.gather(*[_one(ip, port) for ip, port in hosts])

def _health_monitor_loop(once=False):
    """后台健康监控线程：定期检查收藏的服务器，状态/人数变化时记录，一轮汇总发一封邮件。
    once=True 时只跑一轮就返回（供 Web "立即检查"按钮调用）。"""
    import asyncio
    from scanner.async_probe import async_slp_probe
    db_path = config.get("db_path", "mcscanner.db")
    _log(f"[健康监控] {'启动单次手动检查' if once else '启动定时监控'}")
    while not health_monitor["stop_event"].is_set():
        # 每轮重读配置，Web 面板改完下一轮即生效，无需重启
        #   health_probe_concurrency: 同时探测的最大服务器数（默认3，保守温和）
        #   health_probe_ip_gap:      同一IP两次探测最小间隔秒（MC connection-throttle 默认4s）
        #   health_interval:          每轮间隔秒数（默认300，最小60）
        probe_concurrency = max(1, min(int(config.get("health_probe_concurrency", 8)), 20))
        probe_ip_gap = max(0.0, float(config.get("health_probe_ip_gap", 1.5)))
        probe_interval = max(60, int(config.get("health_interval", 300)))
        health_monitor["interval"] = probe_interval
        # 本轮收集到变化的服务器（用于汇总邮件）
        changed_servers = []  # [{ip, port, prev, curr, joined, left, player_names, new_players, left_players}]
        try:
            # 从收藏列表获取服务器
            targets = []
            try:
                from storage.favorites import filter_favorites
                favs = filter_favorites()
                targets = [(f['ip'], f['port']) for f in favs]
            except Exception:
                # 兜底：直接读收藏文件（与 favorites 模块默认路径一致）
                fav_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'favorites.json')
                if os.path.exists(fav_file):
                    try:
                        with open(fav_file, 'r', encoding='utf-8') as f:
                            favs = json.load(f)
                        if isinstance(favs, list):
                            targets = [(f['ip'], f['port']) for f in favs]
                        elif isinstance(favs, dict) and 'servers' in favs:
                            targets = [(f['ip'], f['port']) for f in favs['servers']]
                    except Exception:
                        pass
            # 也从数据库取有人过的服务器（health_monitor_db_extra=false 时只监控收藏）
            if config.get("health_monitor_db_extra", True):
                conn = None
                try:
                    conn = sqlite3.connect(db_path)
                    rows = conn.execute("SELECT ip, port FROM servers WHERE players_online > 0 LIMIT 20").fetchall()
                    for ip, port in rows:
                        if (ip, port) not in targets:
                            targets.append((ip, port))
                except Exception:
                    pass
                finally:
                    if conn:
                        conn.close()

            # 清理已不在监控列表中的残留状态（收藏删除后不留脏数据）
            valid_keys = {f"{ip}:{port}" for ip, port in targets}
            for k in list(health_monitor["status"].keys()):
                if k not in valid_keys:
                    del health_monitor["status"][k]
            for k in list(health_monitor.get("last_players", {}).keys()):
                if k not in valid_keys:
                    del health_monitor["last_players"][k]
            _log(f"[健康监控] 本轮目标数: {len(targets)}, 并发{probe_concurrency} 同IP间隔{probe_ip_gap}s")

            # 逐台探测、逐台更新（扫一个报一个，不用等全部跑完）
            async def _probe_stream():
                sem = asyncio.Semaphore(max(1, probe_concurrency))
                last_hit = {}
                async def _one(ip, port):
                    async with sem:
                        if probe_ip_gap > 0:
                            while True:
                                now = asyncio.get_event_loop().time()
                                wait = last_hit.get(ip, 0.0) + probe_ip_gap - now
                                if wait <= 0:
                                    last_hit[ip] = now
                                    break
                                await asyncio.sleep(wait)
                        try:
                            return (ip, port, await async_slp_probe(ip, port, timeout=4.0))
                        except Exception:
                            return (ip, port, None)
                for fut in asyncio.as_completed([_one(ip, port) for ip, port in targets]):
                    ip, port, r = await fut
                    _process_one(ip, port, r)

            def _process_one(ip, port, r):
                key = f"{ip}:{port}"
                try:
                    if r and r.get("state") == "up":
                        try:
                            from storage.favorites import update_from_probe
                            update_from_probe(ip, port, r)
                        except Exception:
                            pass
                    online = r.get('online', 0) if r else 0
                    online_flag = bool(r and r.get("state") == "up")
                    prev = health_monitor["status"].get(key, {})
                    prev_online = prev.get('players', 0)
                    prev_flag = prev.get('online', False)
                    player_names = []
                    if r:
                        sample = r.get('sample', [])
                        if isinstance(sample, list):
                            player_names = [p.get('name', '') for p in sample if isinstance(p, dict) and p.get('name')]
                    if r and online > 0:
                        conn = None
                        try:
                            conn = sqlite3.connect(db_path)
                            conn.execute(
                                'INSERT INTO server_popularity (ip, port, players_online, players_max, recorded_at) VALUES (?,?,?,?,?)',
                                (ip, port, online, r.get('max', 0), datetime.now(timezone.utc).isoformat())
                            )
                            conn.commit()
                        except Exception:
                            pass
                        finally:
                            if conn:
                                conn.close()
                    prev_players = set(health_monitor.get("last_players", {}).get(key, []))
                    curr_players = set(player_names)
                    new_players = list(curr_players - prev_players)
                    left_players = list(prev_players - curr_players)
                    if online_flag != prev_flag:
                        event = {
                            "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            "ip": ip, "port": port,
                            "from": prev_online, "to": online,
                            "joined": len(new_players), "left": len(left_players),
                            "new_players": new_players, "left_players": left_players,
                            "type": "up" if online_flag else "down"
                        }
                        health_monitor["events"].insert(0, event)
                        health_monitor["events"] = health_monitor["events"][:100]
                        changed_servers.append({
                            "ip": ip, "port": port,
                            "prev": prev_online, "curr": online,
                            "joined": len(new_players), "left": len(left_players),
                            "player_names": player_names,
                            "new_players": new_players, "left_players": left_players,
                        })
                        _log(f"[健康监控] {ip}:{port} 状态变化: {'在线' if online_flag else '离线'} ({prev_online}→{online}人)")
                    elif online != prev_online:
                        event = {
                            "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            "ip": ip, "port": port,
                            "from": prev_online, "to": online,
                            "joined": len(new_players), "left": len(left_players),
                            "new_players": new_players, "left_players": left_players,
                            "type": "change"
                        }
                        health_monitor["events"].insert(0, event)
                        health_monitor["events"] = health_monitor["events"][:100]
                        changed_servers.append({
                            "ip": ip, "port": port,
                            "prev": prev_online, "curr": online,
                            "joined": len(new_players), "left": len(left_players),
                            "player_names": player_names,
                            "new_players": new_players, "left_players": left_players,
                        })
                        _log(f"[健康监控] {ip}:{port} 人数变化: {prev_online}→{online} (进{len(new_players)}走{len(left_players)})")
                    if "last_players" not in health_monitor:
                        health_monitor["last_players"] = {}
                    health_monitor["last_players"][key] = player_names
                    health_monitor["status"][key] = {
                        "online": online_flag, "players": online,
                        "prev_players": prev_online,
                        "joined": len(new_players), "left": len(left_players),
                        "player_names": player_names,
                        "last_check": datetime.now().strftime('%H:%M:%S')
                    }
                except Exception:
                    pass

            if targets:
                asyncio.run(_probe_stream())
            # 一轮检查结束，汇总发送一封邮件（有人数变化就发）
            if changed_servers:
                try:
                    from core.notifier import send_email
                    email_enabled = config.get("email_enabled", False)
                    email_to = config.get("email_to", "")
                    if email_enabled and email_to:
                        lines = [f"<h2>服务器人数变化（共{len(changed_servers)}个）</h2>"]
                        for s in changed_servers:
                            addr = f"{s['ip']}:{s['port']}"
                            delta = s['curr'] - s['prev']
                            delta_str = f"+{delta}" if delta > 0 else str(delta)
                            delta_color = "#e94560" if delta > 0 else "#4caf50"
                            lines.append(f"<p><b>{addr}</b> - {s['prev']}人 → <span style='color:{delta_color}'>{s['curr']}人 ({delta_str})</span></p>")
                            lines.append(f"<p style='margin-left:20px;color:#666;'>进了 {s['joined']} 人，走了 {s['left']} 人</p>")
                            if s['player_names']:
                                lines.append(f"<p style='margin-left:20px;color:#888;'>当前玩家: {', '.join(_html_escape(p) for p in s['player_names'])}</p>")
                            if s['new_players']:
                                lines.append(f"<p style='margin-left:20px;color:#e94560;'>新增: {', '.join(_html_escape(p) for p in s['new_players'])}</p>")
                            if s['left_players']:
                                lines.append(f"<p style='margin-left:20px;color:#999;'>离开: {', '.join(_html_escape(p) for p in s['left_players'])}</p>")
                            lines.append("<hr style='border:none;border-top:1px solid #eee;'>")
                        body = "\n".join(lines)
                        ok, err = send_email(
                            f"[MC监控] {len(changed_servers)}个服务器人数变化",
                            body, html=True
                        )
                        _log(f"[健康监控] 汇总邮件推送: {len(changed_servers)}个服, success={ok} error={err}")
                    else:
                        _log(f"[健康监控] 邮件未推送: enabled={email_enabled} to={email_to}")
                except Exception as e:
                    import traceback
                    _log(f"[健康监控] 汇总邮件异常: {e}\n{traceback.format_exc()}")
        except Exception as e:
            _log(f"[健康监控] 错误: {e}")
        finally:
            health_monitor["last_check"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # 手动单次检查：跑完一轮就退出，不进入等待
        if once:
            return
        # 等待间隔，可被中断
        health_monitor["stop_event"].wait(health_monitor["interval"])


