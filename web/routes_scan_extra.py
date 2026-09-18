# -*- coding: utf-8 -*-
"""Routes: scan_extra"""
from flask import request, jsonify
try:
    from web import state
except ImportError:
    import state  # type: ignore


def register(app):
    def _log(msg):
        state.log_scan(msg)
    def _get_web_token():
        return state.get_web_token()
    def _safe_db_path(path):
        return state.safe_db_path(path)
    def parse_ports_spec(ports_spec):
        return state.parse_ports_spec(ports_spec)


    @app.route('/api/rescan')
    def rescan_list():
        db_path = request.args.get("db_path", "mcscanner.db")
        action = request.args.get("action", "list")
        limit = int(request.args.get("limit", 100))
        from storage import rescan as rescan_db
        rescan_db.init_rescan_queue(db_path)
        if action == "stats":
            return jsonify(rescan_db.get_stats(db_path))
        if action == "due":
            due = rescan_db.get_due_rescans(db_path, limit=limit)
            return jsonify({"total": len(due), "items": due})
        all_items = rescan_db.get_all_rescans(db_path, limit=limit)
        return jsonify({"total": len(all_items), "items": all_items, "stats": rescan_db.get_stats(db_path)})

    @app.route('/api/rescan/run', methods=['POST'])
    def rescan_run():
        data = request.json or {}
        db_path = data.get("db_path", "mcscanner.db")
        limit = int(data.get("limit", 50))
        from storage import rescan as rescan_db
        from scanner.engine import ScanEngine
        rescan_db.init_rescan_queue(db_path)
        due = rescan_db.get_due_rescans(db_path, limit=limit)
        if not due:
            return jsonify({"status": "no_due", "count": 0})
        _log(f"智能重扫开始: {len(due)} 个到期目标")
        engine = ScanEngine(db_path=db_path, workers=16, timeout=4.0, rescan_enabled=True)
        results = []
        for item in due:
            try:
                r = engine.probe_one(item["ip"], item["port"])
                results.append(r)
            except Exception:
                continue
        up = sum(1 for r in results if r.get("state") == "up")
        _log(f"智能重扫完成: {len(results)} 个目标, {up} 个在线")
        return jsonify({"status": "completed", "total": len(results), "up": up})

    @app.route('/api/rescan/clear', methods=['POST'])
    def rescan_clear():
        data = request.json or {}
        db_path = data.get("db_path", "mcscanner.db")
        from storage import rescan as rescan_db
        rescan_db.clear_rescan(db_path)
        _log("重扫队列已清空")
        return jsonify({"success": True})

    @app.route('/api/auto_scan/tasks')
    def auto_scan_tasks():
        from core.auto_scanner import auto_scanner
        return jsonify({"tasks": auto_scanner.list_tasks()})

    @app.route('/api/auto_scan/types')
    def auto_scan_types():
        from core.auto_scanner import AutoScanner
        return jsonify({"types": [
            {"value": k, "label": v} for k, v in AutoScanner.TASK_TYPES.items()
        ]})

    @app.route('/api/auto_scan/add', methods=['POST'])
    def auto_scan_add():
        data = request.json or {}
        if not data.get("targets"):
            return jsonify({"success": False, "error": "请指定扫描目标"}), 400
        from core.auto_scanner import auto_scanner
        task_id = auto_scanner.add_task(data)
        if data.get("auto_start", True):
            auto_scanner.start_task(task_id)
        return jsonify({"success": True, "task_id": task_id})

    @app.route('/api/auto_scan/start', methods=['POST'])
    def auto_scan_start():
        data = request.json or {}
        tid = data.get("task_id")
        if not tid:
            return jsonify({"success": False, "error": "请指定task_id"}), 400
        from core.auto_scanner import auto_scanner
        ok = auto_scanner.start_task(tid)
        return jsonify({"success": ok})

    @app.route('/api/auto_scan/stop', methods=['POST'])
    def auto_scan_stop():
        data = request.json or {}
        tid = data.get("task_id")
        if not tid:
            return jsonify({"success": False, "error": "请指定task_id"}), 400
        from core.auto_scanner import auto_scanner
        auto_scanner.stop_task(tid)
        return jsonify({"success": True})

    @app.route('/api/auto_scan/remove', methods=['POST'])
    def auto_scan_remove():
        data = request.json or {}
        tid = data.get("task_id")
        if not tid:
            return jsonify({"success": False, "error": "请指定task_id"}), 400
        from core.auto_scanner import auto_scanner
        auto_scanner.remove_task(tid)
        return jsonify({"success": True})

    @app.route('/api/auto_scan/logs')
    def auto_scan_logs():
        tid = request.args.get("task_id")
        from core.auto_scanner import auto_scanner
        return jsonify({"logs": auto_scanner.get_logs(tid)})

