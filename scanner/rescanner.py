# -*- coding: utf-8 -*-
"""
智能重扫调度器（v3.2.1 新增，融合 matscan 特性）。
封装 storage/rescan.py 的数据库操作，提供高层调度接口。
可在扫描引擎中自动调用，也可通过 CLI 手动管理。
"""
import time
from storage import rescan as rescan_db
from storage import player_history as ph_db


class RescanScheduler:
    """智能重扫调度器。"""

    def __init__(self, db_path: str = "mcscanner.db", enabled: bool = True):
        self.db_path = db_path
        self.enabled = enabled
        # 确保表存在
        rescan_db.init_rescan_queue(db_path)

    def update(self, result: dict):
        """
        根据扫描结果更新重扫计划。
        result: {"ip", "port", "state", "auth", "players_online", "player_list", ...}
        """
        if not self.enabled:
            return
        ip = result.get("ip", "")
        port = result.get("port", 0)
        if not ip or not port:
            return

        # 更新重扫队列
        strategy = rescan_db.update_rescan(self.db_path, ip, port, result)

        # 更新玩家历史
        player_list = result.get("player_list") or result.get("sample") or []
        if player_list:
            ph_db.update_players(self.db_path, ip, port, player_list)

        return strategy

    def get_due(self, limit: int = 100) -> list:
        """获取到期需要重扫的目标。"""
        return rescan_db.get_due_rescans(self.db_path, limit=limit)

    def get_all(self, limit: int = 200) -> list:
        """获取全部重扫计划。"""
        return rescan_db.get_all_rescans(self.db_path, limit=limit)

    def remove(self, ip: str, port: int):
        """移除某个目标的重扫计划。"""
        rescan_db.remove_rescan(self.db_path, ip, port)

    def clear(self):
        """清空重扫队列。"""
        rescan_db.clear_rescan(self.db_path)

    def stats(self) -> dict:
        """获取重扫队列统计。"""
        return rescan_db.get_stats(self.db_path)

    def run_rescan(self, probe_func, limit: int = 50, timeout: float = 4.0):
        """
        执行到期重扫。
        probe_func: 接收 (ip, port) 返回扫描结果的函数
        """
        if not self.enabled:
            return []
        due = self.get_due(limit=limit)
        if not due:
            return []
        results = []
        for item in due:
            try:
                result = probe_func(item["ip"], item["port"])
                if result:
                    self.update(result)
                    results.append(result)
            except Exception:
                continue
        return results
