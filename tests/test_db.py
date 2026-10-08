#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""storage/db.py 回归测试：连接池回收、并发初始化、JSON 合法性与分页边界。"""
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage import db


class TestDbRobustness(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        db.init_db(self.db_path)

    def tearDown(self):
        db.close_all()   # 先关连接再删文件，避免残留 -wal/-shm
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_connection_pool_is_capped(self):
        for i in range(30):
            db.get_conn(os.path.join(self.tmp, f"pool{i}.db"))
        self.assertLessEqual(len(getattr(db._local, "conns", {})),
                             db._MAX_CONNS_PER_THREAD)

    def test_close_conn_allows_reopen(self):
        db.close_conn(self.db_path)
        db.get_conn(self.db_path).execute("SELECT 1")   # 不能拿到已关闭的连接

    def test_init_db_concurrent(self):
        path = os.path.join(self.tmp, "concurrent.db")
        errors = []

        def run():
            try:
                db.init_db(path)
            except Exception as e:
                errors.append(repr(e))

        threads = [threading.Thread(target=run) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])

    def test_json_fields_never_invalid(self):
        db.upsert_server(self.db_path, {
            "ip": "1.1.1.1", "port": 25565, "players_online": 1,
            "mods": [{"name": "x" * 500} for _ in range(50)],
            "forge_channels": [{"ch": "y" * 200} for _ in range(50)],
            "fingerprint": {"data": "z" * 5000},
        })
        row = db.query(self.db_path, limit=10)[0]
        # 按字符截断的旧实现会让这些字段变成非法 JSON，读取端只能静默回退成空
        self.assertIsInstance(row["mods"], list)
        self.assertIsInstance(row["forge_channels"], list)
        self.assertIsInstance(row["fingerprint"], dict)

    def test_query_limit_is_bounded(self):
        db.upsert_many(self.db_path,
                       [{"ip": f"2.2.2.{i}", "port": 25565} for i in range(20)])
        with patch.object(db, "_MAX_QUERY_LIMIT", 5):
            # LIMIT -1 在原实现里等于无上限
            self.assertEqual(len(db.query(self.db_path, limit=-1)), 5)
            self.assertEqual(len(db.query(self.db_path, limit=10 ** 9)), 5)
            self.assertEqual(len(db.query(self.db_path, limit=3)), 3)
        self.assertEqual(len(db.query(self.db_path, limit=5, offset=-3)), 5)


if __name__ == "__main__":
    unittest.main()
