#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机器人登录测试。
验证完整登录流程（握手 → Login → Configuration → Play）。
"""
import sys
import os
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.bot import MCBot, join_and_warn
from tests.mock_server import MockMCServer


class TestBot(unittest.TestCase):
    """机器人功能测试"""

    @classmethod
    def setUpClass(cls):
        cls.server = MockMCServer(mode="cracked", protocol=767, version_name="1.21.1").start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_bot_connect(self):
        """测试机器人连接登录"""
        bot = MCBot("127.0.0.1", self.server.port, protocol_version=767,
                    username="TestBot", timeout=5.0)
        try:
            bot.connect()
            self.assertEqual(bot.state, "play")
            self.assertEqual(bot.protocol_version, 767)
        finally:
            bot.close()

    def test_bot_send_chat(self):
        """测试发送聊天消息"""
        bot = MCBot("127.0.0.1", self.server.port, protocol_version=767,
                    username="TestBot", timeout=5.0)
        try:
            bot.connect()
            bot.send_chat("Hello from test")
            # 如果没抛异常就算成功
        finally:
            bot.close()

    def test_join_and_warn(self):
        """测试 join_and_warn 完整流程"""
        result = join_and_warn("127.0.0.1", self.server.port,
                               username="TestBot", messages=["Test message"],
                               timeout=5.0, message_delay=0.1)
        self.assertTrue(result.success)
        self.assertTrue(result.is_offline)
        self.assertEqual(result.auth_mode, "offline")
        self.assertGreaterEqual(result.messages_sent, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
