# -*- coding: utf-8 -*-
"""Health monitor loop."""
import os, json, time, sqlite3
from datetime import datetime, timezone
import config, logger
from storage import favorites
try:
    from web import state
except ImportError:
    import state  # type: ignore
health_monitor = state.health_monitor
scan_lock = state.scan_lock

def _log(msg):
    state.log_scan(msg)

def _health_monitor_loop():
    """后台健康监控线程：定期检查收藏的服务器，人数变化时记录，一轮汇总发一封邮件"""
    _log("[健康监控] 启动，间隔5分钟")
    while not health_monitor["stop_event"].is_set():
        # 本轮收集到的人数变化服务器（用于汇总邮件）
        changed_servers = []  # [{ip, port, prev, curr, joined, left, player_names, new_players, left_players}]
        try:
            # 从收藏列表获取服务器
            targets = []
            try:
                from storage.favorites import filter_favorites
                favs = filter_favorites()
                targets = [(f['ip'], f['port']) for f in favs]
            except Exception:
                # 兜底：直接读文件
                fav_file = 'favorites.json'
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
            # 也从数据库取有人过的服务器
            try:
                conn = sqlite3.connect('mcscanner.db')
                rows = conn.execute("SELECT ip, port FROM servers WHERE players_online > 0 LIMIT 20").fetchall()
                conn.close()
                for ip, port in rows:
                    if (ip, port) not in targets:
                        targets.append((ip, port))
            except Exception:
                pass

            for ip, port in targets:
                if health_monitor["stop_event"].is_set():
                    break
                try:
                    import asyncio
                    from scanner.async_probe import async_slp_probe
                    r = asyncio.run(async_slp_probe(ip, port, timeout=4))
                    key = f"{ip}:{port}"
                    online = r.get('online', 0) if r else 0
                    prev = health_monitor["status"].get(key, {})
                    prev_online = prev.get('players', 0)
                    # 获取玩家列表
                    player_names = []
                    if r:
                        sample = r.get('sample', [])
                        if isinstance(sample, list):
                            player_names = [p.get('name', '') for p in sample if isinstance(p, dict) and p.get('name')]
                    # 记录人数趋势
                    if r and online > 0:
                        try:
                            conn = sqlite3.connect('mcscanner.db')
                            conn.execute(
                                'INSERT INTO server_popularity (ip, port, players_online, players_max, recorded_at) VALUES (?,?,?,?,?)',
                                (ip, port, online, r.get('max', 0), datetime.now(timezone.utc).isoformat())
                            )
                            conn.commit()
                            conn.close()
                        except Exception:
                            pass
                    # 对比玩家进出
                    prev_players = set(health_monitor.get("last_players", {}).get(key, []))
                    curr_players = set(player_names)
                    new_players = list(curr_players - prev_players)
                    left_players = list(prev_players - curr_players)
                    # 检测变化（只要人数变了就记录，不只是0→有人）
                    if online != prev_online:
                        event = {
                            "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            "ip": ip, "port": port,
                            "from": prev_online, "to": online,
                            "joined": len(new_players),
                            "left": len(left_players),
                            "new_players": new_players,
                            "left_players": left_players,
                            "type": "up" if online > prev_online else "down"
                        }
                        health_monitor["events"].insert(0, event)
                        health_monitor["events"] = health_monitor["events"][:100]
                        # 收集人数变化的服务器，一轮结束汇总发邮件
                        changed_servers.append({
                            "ip": ip, "port": port,
                            "prev": prev_online, "curr": online,
                            "joined": len(new_players), "left": len(left_players),
                            "player_names": player_names,
                            "new_players": new_players,
                            "left_players": left_players,
                        })
                        _log(f"[健康监控] {ip}:{port} 人数变化: {prev_online}→{online} (进{len(new_players)}走{len(left_players)})")
                    # 更新上次玩家列表
                    if "last_players" not in health_monitor:
                        health_monitor["last_players"] = {}
                    health_monitor["last_players"][key] = player_names
                    health_monitor["status"][key] = {
                        "online": bool(r), "players": online,
                        "prev_players": prev_online,
                        "joined": len(new_players), "left": len(left_players),
                        "player_names": player_names,
                        "last_check": datetime.now().strftime('%H:%M:%S')
                    }
                except Exception:
                    pass
                time.sleep(0.5)
            health_monitor["last_check"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

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
                                lines.append(f"<p style='margin-left:20px;color:#888;'>当前玩家: {', '.join(s['player_names'])}</p>")
                            if s['new_players']:
                                lines.append(f"<p style='margin-left:20px;color:#e94560;'>新增: {', '.join(s['new_players'])}</p>")
                            if s['left_players']:
                                lines.append(f"<p style='margin-left:20px;color:#999;'>离开: {', '.join(s['left_players'])}</p>")
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
        # 等待间隔，可被中断
        health_monitor["stop_event"].wait(health_monitor["interval"])


