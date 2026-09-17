# -*- coding: utf-8 -*-
"""Routes: data"""
from flask import request, jsonify, Response, send_from_directory
import os, sys, json, time, threading
from datetime import datetime
from collections import deque
import config, logger
try:
    from web import state
except ImportError:
    import state  # type: ignore


def register(app):
    scan_state = state.scan_state
    scan_lock = state.scan_lock
    scan_stop_event = state.scan_stop_event
    observer_sessions = state.observer_sessions
    observer_lock = getattr(state, "observer_lock", state.scan_lock)
    health_monitor = state.health_monitor
    _ai_bots = state._ai_bots
    def _log(msg):
        state.log_scan(msg)
    def _get_web_token():
        return state.get_web_token()
    def _safe_db_path(path):
        return state.safe_db_path(path)
    def parse_ports_spec(ports_spec):
        return state.parse_ports_spec(ports_spec)


    @app.route('/api/db/query')
    def db_query():
        db_path = _safe_db_path(request.args.get("db_path", "mcscanner.db"))
        auth = request.args.get("auth")
        modded = request.args.get("modded")
        search = request.args.get("search")
        try:
            limit = int(request.args.get("limit", 100))
        except (ValueError, TypeError):
            limit = 100
        try:
            offset = int(request.args.get("offset", 0))
        except (ValueError, TypeError):
            offset = 0
        try:
            modded_val = int(modded) if modded else None
        except (ValueError, TypeError):
            modded_val = None
        if not os.path.exists(db_path):
            return jsonify({"total": 0, "results": []})
        rows = db.query(db_path, auth=auth, modded=modded_val,
                         search=search, limit=limit, offset=offset)
        total = db.count(db_path, auth=auth, modded=modded_val, search=search)
        return jsonify({"total": total, "results": rows})

    @app.route('/api/db/export')
    def db_export():
        """导出扫描数据库，支持 txt/csv/json/html 格式，带筛选条件"""
        db_path = _safe_db_path(request.args.get("db_path", "mcscanner.db"))
        fmt = request.args.get("format", "txt").lower()
        auth = request.args.get("auth")
        modded = request.args.get("modded")
        search = request.args.get("search")
        only_online = request.args.get("only_online", "0")
        try:
            modded_val = int(modded) if modded else None
        except (ValueError, TypeError):
            modded_val = None
        if not os.path.exists(db_path):
            return jsonify({"error": "数据库不存在"}), 404

        # 导出最多20000条，避免文件过大
        rows = db.query(db_path, auth=auth, modded=modded_val, search=search, limit=20000, offset=0)
        if only_online == "1":
            rows = [r for r in rows if r.get("players_online", 0) > 0]
        total = len(rows)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ts = int(time.time())

        if fmt == "json":
            return jsonify({"total": total, "exported_at": now, "results": rows})

        if fmt == "csv":
            lines = ["IP,端口,版本,协议,人数,延迟,验证,核心,Mod,MOTD"]
            for r in rows:
                ip = r.get("ip", "")
                port = r.get("port", 25565)
                ver = (r.get("version") or "").replace(",", " ")
                proto = r.get("proto", "")
                players = f"{r.get('players_online', 0)}/{r.get('players_max', 0)}"
                ping = r.get("ping_ms", "")
                auth_v = r.get("auth", "")
                core = (r.get("core_type") or "").replace(",", " ")
                mods = "是" if r.get("is_modded") else "否"
                motd = (r.get("motd") or "").replace(",", " ").replace("\n", " ")
                lines.append(f"{ip},{port},{ver},{proto},{players},{ping},{auth_v},{core},{mods},{motd}")
            return Response("\n".join(lines), mimetype="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f"attachment; filename=scan_results_{ts}.csv"})

        if fmt == "html":
            rows_html = ""
            for r in rows:
                ip = r.get("ip", "")
                port = r.get("port", 25565)
                ver = r.get("version") or "-"
                players = f"{r.get('players_online', 0)}/{r.get('players_max', 0)}"
                online = r.get("players_online", 0)
                pcolor = "#e94560" if online > 0 else "#555"
                auth_v = r.get("auth") or "-"
                core = r.get("core_type") or "-"
                motd = (r.get("motd") or "")[:50]
                rows_html += f"""<tr>
    <td><a href="http://{ip}:{port}" style="color:#00d992;">{ip}:{port}</a></td>
    <td>{ver}</td><td style="color:{pcolor};font-weight:bold;">{players}</td><td>{auth_v}</td><td>{core}</td><td style="color:#888;font-size:12px;">{motd}</td>
    </tr>"""
            html = f"""<!DOCTYPE html>
    <html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>扫描结果导出</title>
    <style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0a0a0a;color:#e0e0e0;font-family:Consolas,Monaco,monospace;padding:20px}}
    .container{{max-width:1100px;margin:0 auto}}
    .header{{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #0f3460;border-radius:12px;padding:24px;margin-bottom:20px}}
    .header h1{{color:#00d992;font-size:22px;margin-bottom:8px}}
    .header .info{{color:#888;font-size:13px}}.header .info span{{color:#e94560}}
    table{{width:100%;border-collapse:collapse;background:#111;border:1px solid #222;border-radius:12px;overflow:hidden}}
    th{{background:#0f3460;color:#fff;padding:10px;text-align:left;font-size:13px}}
    td{{padding:8px 10px;border-bottom:1px solid #1a1a1a;font-size:13px}}
    tr:hover{{background:#161616}}
    .footer{{text-align:center;color:#444;font-size:12px;margin-top:16px}}</style>
    </head><body><div class="container">
    <div class="header"><h1>MC扫描结果</h1>
    <div class="info">共 <span>{total}</span> 个服务器 | 导出时间: <span>{now}</span></div>
    </div>
    <table><tr><th>地址</th><th>版本</th><th>人数</th><th>验证</th><th>核心</th><th>MOTD</th></tr>{rows_html}</table>
    <div class="footer">Generated by mc-scanner-v3</div>
    </div></body></html>"""
            return Response(html, mimetype="text/html; charset=utf-8",
                            headers={"Content-Disposition": f"attachment; filename=scan_results_{ts}.html"})

        # 默认 TXT
        lines = [f"MC扫描结果导出", f"共 {total} 个服务器", f"导出时间: {now}", "=" * 60, ""]
        for i, r in enumerate(rows, 1):
            ip = r.get("ip", "")
            port = r.get("port", 25565)
            ver = r.get("version") or "?"
            players = f"{r.get('players_online', 0)}/{r.get('players_max', 0)}"
            auth_v = r.get("auth") or "?"
            core = r.get("core_type") or "?"
            motd = (r.get("motd") or "")[:60]
            lines.append(f"[{i}] {ip}:{port}")
            lines.append(f"    版本: {ver} | 人数: {players} | 验证: {auth_v} | 核心: {core}")
            if motd:
                lines.append(f"    MOTD: {motd}")
            lines.append("")
        return Response("\n".join(lines), mimetype="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=scan_results_{ts}.txt"})

    @app.route('/api/server/popularity')
    def server_popularity():
        """查询服务器人数历史趋势"""
        ip = request.args.get("ip", "")
        port = request.args.get("port", type=int)
        hours = request.args.get("hours", type=int, default=24)
        if not ip or not port:
            return jsonify({"error": "ip和port必填"}), 400
        db_path = _safe_db_path(request.args.get("db_path", "mcscanner.db"))
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # 按小时聚合，取每小时最大人数
        rows = conn.execute(
            """SELECT strftime('%Y-%m-%d %H:00', recorded_at) as hour,
                      MAX(players_online) as online, MAX(players_max) as max_p
               FROM server_popularity
               WHERE ip=? AND port=? AND recorded_at > datetime('now', ?)
               GROUP BY hour ORDER BY hour ASC""",
            (ip, port, f'-{hours} hours')
        ).fetchall()
        conn.close()
        return jsonify({
            "ip": ip, "port": port, "hours": hours,
            "data": [{"time": r["hour"], "online": r["online"], "max": r["max_p"]} for r in rows]
        })

    @app.route('/api/db/stats')
    def db_stats():
        db_path = _safe_db_path(request.args.get("db_path", "mcscanner.db"))
        if not os.path.exists(db_path):
            return jsonify({"total": 0, "by_auth": {}, "online_servers": 0, "by_version": {}})
        return jsonify(db.stats(db_path))

    @app.route('/api/history')
    def history():
        with scan_lock:
            return jsonify({"history": scan_state["history"]})

    @app.route('/api/favorites')
    def fav_list():
        tag = request.args.get("tag")
        search = request.args.get("search", "")
        favs = favorites.filter_favorites(tag=tag or None, search=search or None)
        return jsonify({"total": len(favs), "favorites": favs, "tags": favorites.get_all_tags()})

    @app.route('/api/favorites/add', methods=['POST'])
    def fav_add():
        data = request.json or {}
        ip = data.get("ip")
        port = int(data.get("port") or 25565)
        tags = data.get("tags", [])
        note = data.get("note", "")
        info = data.get("info")
        if not ip:
            return jsonify({"error": "IP 不能为空"}), 400
        fav = favorites.add_favorite(ip, port, tags=tags, note=note, info=info)
        _log(f"收藏添加: {ip}:{port}")
        return jsonify({"success": True, "favorite": fav})

    @app.route('/api/favorites/remove', methods=['POST'])
    def fav_remove():
        data = request.json or {}
        ip = data.get("ip")
        port = int(data.get("port") or 25565)
        ok = favorites.remove_favorite(ip, port)
        if ok:
            _log(f"收藏移除: {ip}:{port}")
        return jsonify({"success": ok})

    @app.route('/api/favorites/tags', methods=['POST'])
    def fav_tags():
        data = request.json or {}
        ip = data.get("ip")
        port = int(data.get("port") or 25565)
        tags = data.get("tags", [])
        fav = favorites.update_tags(ip, port, tags)
        return jsonify({"success": fav is not None, "favorite": fav})

    @app.route('/api/favorites/note', methods=['POST'])
    def fav_note():
        data = request.json or {}
        ip = data.get("ip")
        port = int(data.get("port") or 25565)
        note = data.get("note", "")
        fav = favorites.update_note(ip, port, note)
        return jsonify({"success": fav is not None, "favorite": fav})

    @app.route('/api/favorites/import', methods=['POST'])
    def fav_import():
        if 'file' not in request.files:
            return jsonify({"error": "请选择文件"}), 400
        f = request.files['file']
        tmp_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'fav_import_' + str(int(time.time())) + '.txt')
        f.save(tmp_path)
        try:
            count = favorites.import_from_file(tmp_path)
            _log(f"收藏导入: {count} 个")
            return jsonify({"success": True, "count": count})
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    @app.route('/api/favorites/export')
    def fav_export():
        """导出收藏列表，支持 txt/csv/json/html 格式"""
        fmt = request.args.get("format", "txt").lower()
        tag = request.args.get("tag")
        search = request.args.get("search", "")
        favs = favorites.filter_favorites(tag=tag or None, search=search or None)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ts = int(time.time())

        if fmt == "json":
            return jsonify({"total": len(favs), "exported_at": now, "favorites": favs})

        if fmt == "csv":
            lines = ["IP,端口,版本,人数,验证,标签,备注,MOTD"]
            for f in favs:
                info = f.get("last_info") or {}
                ip = f.get("ip", "")
                port = f.get("port", 25565)
                ver = (info.get("version") or "").replace(",", " ")
                players = f"{info.get('players_online', 0)}/{info.get('players_max', 0)}"
                auth = info.get("auth", "")
                tags = "|".join(f.get("tags", []))
                note = (f.get("note") or "").replace(",", " ").replace("\n", " ")
                motd = (info.get("motd") or "").replace(",", " ").replace("\n", " ")
                lines.append(f"{ip},{port},{ver},{players},{auth},{tags},{note},{motd}")
            return Response("\n".join(lines), mimetype="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f"attachment; filename=favorites_{ts}.csv"})

        if fmt == "html":
            rows = ""
            for f in favs:
                info = f.get("last_info") or {}
                ip = f.get("ip", "")
                port = f.get("port", 25565)
                ver = info.get("version") or "-"
                players = f"{info.get('players_online', 0)}/{info.get('players_max', 0)}"
                auth = info.get("auth") or "-"
                tags = " ".join(f'<span style="background:#0f3460;padding:2px 6px;border-radius:3px;font-size:11px;">{t}</span>' for t in f.get("tags", []))
                note = f.get("note") or ""
                motd = (info.get("motd") or "")[:50]
                rows += f"""<tr>
    <td><a href="http://{ip}:{port}" style="color:#00d992;">{ip}:{port}</a></td>
    <td>{ver}</td><td>{players}</td><td>{auth}</td><td>{tags}</td><td>{note}</td><td style="color:#888;font-size:12px;">{motd}</td>
    </tr>"""
            html = f"""<!DOCTYPE html>
    <html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>收藏列表导出</title>
    <style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0a0a0a;color:#e0e0e0;font-family:Consolas,Monaco,monospace;padding:20px}}
    .container{{max-width:1100px;margin:0 auto}}
    .header{{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #0f3460;border-radius:12px;padding:24px;margin-bottom:20px}}
    .header h1{{color:#00d992;font-size:22px;margin-bottom:8px}}
    .header .info{{color:#888;font-size:13px}}.header .info span{{color:#e94560}}
    table{{width:100%;border-collapse:collapse;background:#111;border:1px solid #222;border-radius:12px;overflow:hidden}}
    th{{background:#0f3460;color:#fff;padding:10px;text-align:left;font-size:13px}}
    td{{padding:8px 10px;border-bottom:1px solid #1a1a1a;font-size:13px}}
    tr:hover{{background:#161616}}
    .footer{{text-align:center;color:#444;font-size:12px;margin-top:16px}}</style>
    </head><body><div class="container">
    <div class="header"><h1>MC服务器收藏列表</h1>
    <div class="info">共 <span>{len(favs)}</span> 个服务器 | 导出时间: <span>{now}</span></div>
    </div>
    <table><tr><th>地址</th><th>版本</th><th>人数</th><th>验证</th><th>标签</th><th>备注</th><th>MOTD</th></tr>{rows}</table>
    <div class="footer">Generated by mc-scanner-v3</div>
    </div></body></html>"""
            return Response(html, mimetype="text/html; charset=utf-8",
                            headers={"Content-Disposition": f"attachment; filename=favorites_{ts}.html"})

        # 默认 TXT
        lines = [f"MC服务器收藏列表", f"共 {len(favs)} 个服务器", f"导出时间: {now}", "=" * 60, ""]
        for i, f in enumerate(favs, 1):
            info = f.get("last_info") or {}
            ip = f.get("ip", "")
            port = f.get("port", 25565)
            ver = info.get("version") or "?"
            players = f"{info.get('players_online', 0)}/{info.get('players_max', 0)}"
            auth = info.get("auth") or "?"
            tags = ",".join(f.get("tags", []))
            note = f.get("note") or ""
            motd = (info.get("motd") or "")[:60]
            lines.append(f"[{i}] {ip}:{port}")
            lines.append(f"    版本: {ver} | 人数: {players} | 验证: {auth}")
            if tags:
                lines.append(f"    标签: {tags}")
            if note:
                lines.append(f"    备注: {note}")
            if motd:
                lines.append(f"    MOTD: {motd}")
            lines.append("")
        return Response("\n".join(lines), mimetype="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=favorites_{ts}.txt"})

    @app.route('/api/players')
    def players_history():
        db_path = request.args.get("db_path", "mcscanner.db")
        player_name = request.args.get("name")
        ip = request.args.get("ip")
        port = request.args.get("port", type=int)
        limit = int(request.args.get("limit", 100))
        if not os.path.exists(db_path):
            return jsonify({"total": 0, "players": []})
        from storage import player_history as ph
        players = ph.get_player_history(db_path, player_name=player_name, ip=ip, port=port, limit=limit)
        return jsonify({"total": len(players), "players": players})

    @app.route('/api/players/stats')
    def players_stats():
        db_path = request.args.get("db_path", "mcscanner.db")
        if not os.path.exists(db_path):
            return jsonify({"total_records": 0, "unique_players": 0, "unique_servers": 0})
        from storage import player_history as ph
        return jsonify(ph.get_stats(db_path))

    @app.route('/api/favorites/realtime')
    def favorites_realtime():
        """返回收藏服务器的实时监控状态（当前人数、上次人数、进出玩家）"""
        try:
            from storage.favorites import filter_favorites
            favs = filter_favorites()
        except Exception:
            favs = []
        result = []
        for f in favs:
            key = f"{f['ip']}:{f['port']}"
            st = health_monitor["status"].get(key, {})
            result.append({
                "ip": f['ip'], "port": f['port'],
                "tag": f.get('tag', ''),
                "note": f.get('note', ''),
                "online": st.get("online", False),
                "players": st.get("players", 0),
                "prev_players": st.get("prev_players", 0),
                "joined": st.get("joined", 0),
                "left": st.get("left", 0),
                "player_names": st.get("player_names", []),
                "last_check": st.get("last_check", ""),
            })
        return jsonify({"servers": result, "last_check": health_monitor.get("last_check")})

