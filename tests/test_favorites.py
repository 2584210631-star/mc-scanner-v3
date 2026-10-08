#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收藏模块回归测试：并发原子更新、坏行导入、rescan_all 不持锁做网络 I/O。"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage import favorites


class TestFavoritesRobustness(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "favorites.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_update_favorite_no_lost_update(self):
        favorites.add_favorite("1.1.1.1", 25565, path=self.path)
        favorites.add_favorite("2.2.2.2", 25565, path=self.path)
        # 模拟健康监控只改一项：不能吞掉其它项
        favorites.update_favorite("1.1.1.1", 25565,
                                  lambda f: {**f, "note": "x"}, path=self.path)
        ips = {f["ip"] for f in favorites.load_favorites(self.path)}
        self.assertEqual(ips, {"1.1.1.1", "2.2.2.2"})

    def test_concurrent_add_no_lost_update(self):
        def worker(i):
            for j in range(15):
                favorites.add_favorite(f"10.{i}.0.{j}", 25565, path=self.path)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(favorites.load_favorites(self.path)), 6 * 15)

    def test_import_skips_bad_lines(self):
        src = os.path.join(self.tmp, "import.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("1.2.3.4:25565\n5.6.7.8:notaport\n9.9.9.9:70000\n# 注释\n8.8.8.8\n")
        count, failed = favorites.import_favorites(src, path=self.path)
        self.assertEqual(count, 2)          # 1.2.3.4 与 8.8.8.8（默认端口）
        self.assertEqual(len(failed), 2)    # 端口非数字 / 越界
        # 兼容旧签名：仍然返回 int
        self.assertEqual(favorites.import_from_file(src, path=self.path), 2)
        self.assertEqual(len(favorites.load_favorites(self.path)), 2)

    def test_non_serializable_save_does_not_escape(self):
        favorites.add_favorite("1.1.1.1", 25565, path=self.path)
        # 集合不可 JSON 序列化：不能把异常抛给调用方，文件也要保持合法 JSON
        favorites.update_favorite("1.1.1.1", 25565,
                                  lambda f: {**f, "bad": {1, 2}}, path=self.path)
        with open(self.path, encoding="utf-8") as f:
            self.assertIsInstance(json.load(f), list)

    def test_rescan_all_does_not_hold_lock_during_io(self):
        favorites.add_favorite("1.1.1.1", 25565, path=self.path)

        def slow_probe(ip, port, timeout=5.0):
            time.sleep(0.6)
            return {"state": "up", "version": "1.20"}

        with patch.object(favorites, "slp_probe", slow_probe), \
             patch.object(favorites, "auth_probe", lambda *a, **k: None):
            t = threading.Thread(
                target=lambda: favorites.rescan_all(timeout=0.1, workers=1, path=self.path))
            t.start()
            time.sleep(0.15)    # 让 rescan_all 进入网络探测阶段
            start = time.time()
            favorites.add_favorite("2.2.2.2", 25565, path=self.path)
            elapsed = time.time() - start
            t.join()
        # 网络 I/O 已移出锁：写操作不应等到 0.6s 的探测结束
        self.assertLess(elapsed, 0.4, f"add_favorite 被 rescan_all 阻塞了 {elapsed:.2f}s")
        ips = {f["ip"] for f in favorites.load_favorites(self.path)}
        self.assertEqual(ips, {"1.1.1.1", "2.2.2.2"})


if __name__ == "__main__":
    unittest.main()
