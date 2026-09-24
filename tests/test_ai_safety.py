# -*- coding: utf-8 -*-
"""AI 托管安全测试：命令拦截、API失败退避、记忆清除。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _MockBot:
    def __init__(self):
        self.sent = []
        self.state = "play"

    def send_chat(self, line):
        self.sent.append(line)


def _make_session():
    from core.ai_bot import AIBotSession
    s = AIBotSession("127.0.0.1", 25565, "TestBot", use_premium=False)
    s.bot = _MockBot()
    return s


# ===== 命令拦截（防提示词注入） =====
def test_safe_send_blocks_slash_commands():
    s = _make_session()
    assert s._safe_send_chat("/op hacker") is False
    assert s._safe_send_chat("/stop") is False
    assert s._safe_send_chat("  /give @a diamond") is False
    # 没有任何命令被发出
    assert s.bot.sent == []


def test_safe_send_allows_normal_chat():
    s = _make_session()
    assert s._safe_send_chat("大家好啊") is True
    assert s._safe_send_chat("你可以输入 help 查看") is True  # 不以/开头，安全
    assert s.bot.sent == ["大家好啊", "你可以输入 help 查看"]


def test_safe_send_empty():
    s = _make_session()
    assert s._safe_send_chat("") is False
    assert s._safe_send_chat("   ") is False
    assert s.bot.sent == []


# ===== API 连续失败退避 =====
def test_backoff_after_three_failures():
    s = _make_session()
    assert s._in_api_backoff() is False
    s._record_api_result(False)
    s._record_api_result(False)
    assert s._in_api_backoff() is False  # 2次还不退
    s._record_api_result(False)
    assert s._in_api_backoff() is True   # 3次进入退避
    assert s._should_reply("p", "你好") is False


def test_backoff_reset_on_success():
    s = _make_session()
    for _ in range(3):
        s._record_api_result(False)
    assert s._in_api_backoff() is True
    s._record_api_result(True)
    assert s._in_api_backoff() is False
    assert s._api_fail_count == 0


# ===== 记忆清除 =====
def test_memory_clear_all_and_player(tmp_path, monkeypatch):
    import core.ai_memory as mem
    monkeypatch.chdir(tmp_path)
    mem._long_term = {}
    mem._loaded = True
    mem.update_player_memory("Alice", "我喜欢红石")
    mem.update_player_memory("Bob", "今天天气不错")
    assert mem.get_player_profile("Alice") is not None
    # 清除单个
    assert mem.clear_player("Alice") is True
    assert mem.get_player_profile("Alice") is None
    assert mem.get_player_profile("Bob") is not None
    # 清除不存在的
    assert mem.clear_player("Nobody") is False
    # 清除全部
    n = mem.clear_all_memory()
    assert n == 1
    assert mem.get_player_profile("Bob") is None
