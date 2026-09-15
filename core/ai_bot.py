# -*- coding: utf-8 -*-
"""
AI托管Bot模块。
连接MC服务器后自动监听聊天，用AI回复玩家消息，支持定时主动发言。
"""
import threading
import time
import re
from collections import deque
from datetime import datetime

from core.bot import MCBot
from core.ai_generator import generate_content, split_for_minecraft


class AIBotSession:
    """AI托管Bot会话：连接服务器，AI自动回复聊天"""

    def __init__(self, host, port, username, authme_password=None, timeout=20.0,
                 duration=0, protocol_version=None, ai_config=None):
        self.session_id = ""
        self.host = host
        self.port = port
        self.username = username
        self.authme_password = authme_password
        self.timeout = timeout
        self.duration = duration  # 0=一直运行
        self.protocol_version = protocol_version
        self.bot = None
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.status = "connecting"
        self.error = ""
        self.version_name = ""
        self.start_time = time.time()
        self.connect_time = None

        # AI配置
        cfg = ai_config or {}
        self.api_key = cfg.get("api_key", "")
        self.base_url = cfg.get("base_url", "https://api.openai.com/v1")
        self.model = cfg.get("model", "gpt-3.5-turbo")
        self.persona = cfg.get("persona", "你是一个友好的MC玩家，喜欢和人聊天，说话简短有趣，不超过30字。")
        self.reply_enabled = cfg.get("reply_enabled", True)
        self.reply_cooldown = float(cfg.get("reply_cooldown", 5.0))  # 回复冷却秒数
        self.trigger_keywords = cfg.get("trigger_keywords", [])  # 空=回复所有
        self.auto_talk_enabled = cfg.get("auto_talk_enabled", False)
        self.auto_talk_interval = float(cfg.get("auto_talk_interval", 120.0))  # 主动发言间隔
        self.auto_talk_preset = cfg.get("auto_talk_preset", "novel")  # 主动发言类型

        self.chat_log = deque(maxlen=500)
        self._last_reply_time = 0
        self._last_auto_talk = time.time()
        self._seq = 0

    def _next_seq(self):
        self._seq += 1
        return self._seq

    @staticmethod
    def _ts():
        return datetime.now().strftime("%H:%M:%S")

    def _on_chat(self, text, sender="未知"):
        try:
            with self.lock:
                self.chat_log.append((self._next_seq(), self._ts(), sender, text))
            # 触发AI回复
            if self.reply_enabled and self.bot and self.bot.state == "play":
                self._maybe_reply(sender, text)
        except Exception:
            pass

    def _should_reply(self, sender, text):
        """判断是否应该回复这条消息"""
        now = time.time()
        if now - self._last_reply_time < self.reply_cooldown:
            return False
        # 不回复自己
        if sender == self.username:
            return False
        # 过滤系统消息
        if not text or text.startswith('[') or text.startswith('【'):
            return False
        # 关键词触发
        if self.trigger_keywords:
            if not any(kw in text for kw in self.trigger_keywords):
                return False
        return True

    def _maybe_reply(self, sender, text):
        """异步线程中生成AI回复并发送"""
        if not self._should_reply(sender, text):
            return
        self._last_reply_time = time.time()

        def _reply_worker():
            try:
                prompt = f"{self.persona}\n玩家[{sender}]说：{text}\n请回复："
                result = generate_content(
                    topic=prompt,
                    preset="custom",
                    api_key=self.api_key,
                    base_url=self.base_url,
                    model=self.model,
                    custom_prompt=prompt,
                )
                if result.get("success") and result.get("content"):
                    reply = result["content"].strip()
                    # 截断过长回复
                    if len(reply) > 80:
                        reply = reply[:80]
                    for line in split_for_minecraft(reply):
                        if self.stop_event.is_set():
                            break
                        self.bot.send_chat(line)
                        time.sleep(0.5)
            except Exception:
                pass

        t = threading.Thread(target=_reply_worker, daemon=True)
        t.start()

    def _do_auto_talk(self):
        """定时主动发言"""
        if not self.auto_talk_enabled or not self.bot or self.bot.state != "play":
            return
        now = time.time()
        if now - self._last_auto_talk < self.auto_talk_interval:
            return
        self._last_auto_talk = now

        def _talk_worker():
            try:
                result = generate_content(
                    topic="随机话题",
                    preset=self.auto_talk_preset,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    model=self.model,
                )
                if result.get("success") and result.get("content"):
                    for line in split_for_minecraft(result["content"]):
                        if self.stop_event.is_set():
                            break
                        self.bot.send_chat(line)
                        time.sleep(1.0)
            except Exception:
                pass

        t = threading.Thread(target=_talk_worker, daemon=True)
        t.start()

    def run(self):
        try:
            self.bot = MCBot(host=self.host, port=self.port,
                             username=self.username, timeout=self.timeout,
                             protocol_version=self.protocol_version)
            self.bot.chat_callback = self._on_chat
            self.bot.connect()
            with self.lock:
                self.status = "connected"
                self.version_name = self.bot.version_name if hasattr(self.bot, 'version_name') else ""
                self.connect_time = time.time()
            if self.authme_password:
                try:
                    self.bot.authme_login(self.authme_password, register=False)
                except Exception:
                    pass
            # 保持连接
            while not self.stop_event.is_set():
                if not getattr(self.bot, "connected", True):
                    with self.lock:
                        self.status = "disconnected"
                    return
                if self.duration > 0 and self.connect_time and (time.time() - self.connect_time) >= self.duration:
                    with self.lock:
                        self.status = "stopped"
                    return
                self._do_auto_talk()
                time.sleep(1.0)
        except Exception as e:
            with self.lock:
                self.status = "error"
                self.error = str(e)[:200]

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        try:
            if self.bot:
                self.bot.disconnect()
        except Exception:
            pass

    def send_message(self, message):
        """手动发送消息"""
        if self.bot and self.bot.state == "play":
            for line in split_for_minecraft(message):
                self.bot.send_chat(line)
                time.sleep(0.3)
            return True
        return False

    def get_status(self):
        with self.lock:
            return {
                "session_id": self.session_id,
                "host": self.host,
                "port": self.port,
                "username": self.username,
                "status": self.status,
                "error": self.error,
                "version": self.version_name,
                "uptime": int(time.time() - self.connect_time) if self.connect_time else 0,
                "chat_count": len(self.chat_log),
            }

    def get_chat(self, since=0):
        with self.lock:
            return [{"seq": s, "time": t, "sender": sd, "text": tx}
                    for s, t, sd, tx in self.chat_log if s > since]
