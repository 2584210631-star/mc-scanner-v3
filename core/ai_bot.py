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
import logger as _log
from core.ai_personas import PRESET_PERSONAS

_api_lock = threading.Lock()
_last_api_time = 0.0
API_MIN_INTERVAL = 1.5

def _acquire_api_slot():
    global _last_api_time
    _api_lock.acquire()
    now = time.time()
    wait = API_MIN_INTERVAL - (now - _last_api_time)
    if wait > 0:
        time.sleep(wait)
    _last_api_time = time.time()

def _release_api_slot():
    _api_lock.release()


class AIBotSession:
    def __init__(self, host, port, username, authme_password=None, timeout=20.0,
                 duration=0, protocol_version=None, ai_config=None):
        self.session_id = ""
        self.host = host
        self.port = port
        self.username = username
        self.authme_password = authme_password
        self.timeout = timeout
        self.duration = duration
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
        cfg = ai_config or {}
        self.api_key = cfg.get("api_key", "")
        self.base_url = cfg.get("base_url", "https://api.openai.com/v1")
        self.model = cfg.get("model", "gpt-3.5-turbo")
        self.persona = cfg.get("persona", "你是一个友好的MC玩家，喜欢和人聊天，说话简短有趣，不超过30字。")
        self.reply_enabled = cfg.get("reply_enabled", True)
        self.reply_cooldown = float(cfg.get("reply_cooldown", 2.0))
        self.trigger_keywords = cfg.get("trigger_keywords", [])
        self.auto_talk_enabled = cfg.get("auto_talk_enabled", False)
        self.auto_talk_interval = float(cfg.get("auto_talk_interval", 120.0))
        self.auto_talk_preset = cfg.get("auto_talk_preset", "novel")
        self.topic = cfg.get("topic", "")
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
            state = getattr(self.bot, "state", "unknown")
            _log.debug(f"[AI Bot {self.username}] _on_chat state={state} reply_enabled={self.reply_enabled} sender={sender} text={text[:40]}")
            if self.reply_enabled and self.bot and state == "play":
                self._maybe_reply(sender, text)
            else:
                _log.debug(f"[AI Bot {self.username}] skip reply state={state}")
        except Exception as e:
            _log.warning(f"[AI Bot {self.username}] _on_chat error: {e}")

    def _should_reply(self, sender, text):
        now = time.time()
        if now - self._last_reply_time < self.reply_cooldown:
            return False
        if sender == self.username:
            return False
        if text and (f"]{self.username}:" in text or text.startswith(f"{self.username}:")):
            return False
        if not text:
            return False
        system_patterns = ["加入了游戏", "离开了游戏", "达成了", "完成了挑战", "溃死", "摔死", "烧死", "炸死", "欢迎来到"]
        if any(p in text for p in system_patterns):
            return False
        if text.startswith('/') or text.startswith('Unknown command'):
            return False
        if self.trigger_keywords and not any(kw in text for kw in self.trigger_keywords):
            return False
        return True

    def _maybe_reply(self, sender, text):
        if not self._should_reply(sender, text):
            return
        self._last_reply_time = time.time()
        _log.info(f"[AI Bot {self.username}] reply to {sender}: {text[:40]}")

        def _reply_worker():
            try:
                history_text = ""
                try:
                    recent = list(self.chat_log)[-20:]
                    if len(recent) > 1:
                        history_lines = [f"[{s}] {t}" for seq, ts, s, t in recent[:-1]]
                        history_text = "\n".join(history_lines)
                except Exception:
                    pass
                if history_text:
                    prompt = f"{self.persona}\n\n【最近聊天记录】\n{history_text}\n\n玩家[{sender}]说：{text}\n请结合上下文回复："
                else:
                    prompt = f"{self.persona}\n玩家[{sender}]说：{text}\n请回复："
                _acquire_api_slot()
                try:
                    result = generate_content(topic=prompt, preset="custom", api_key=self.api_key,
                                              base_url=self.base_url, model=self.model, custom_prompt=prompt)
                finally:
                    _release_api_slot()
                if result.get("success") and result.get("text"):
                    reply = result["text"].strip().replace('"', '').replace('「', '').replace('」', '')
                    for line in split_for_minecraft(reply):
                        if self.stop_event.is_set():
                            break
                        self.bot.send_chat(line)
                        time.sleep(0.5)
                elif not result.get("success"):
                    _log.warning(f"[AI Bot] generate failed: {result.get('error', '?')}")
            except Exception as e:
                _log.warning(f"[AI Bot] reply error: {e}")

        threading.Thread(target=_reply_worker, daemon=True).start()

    def _do_auto_talk(self):
        if not self.auto_talk_enabled or not self.bot or self.bot.state != "play":
            return
        now = time.time()
        if now - self._last_auto_talk < self.auto_talk_interval:
            return
        self._last_auto_talk = now

        def _talk_worker():
            try:
                history_text = ""
                try:
                    recent = list(self.chat_log)[-15:]
                    if recent:
                        history_text = "\n".join(f"[{s}] {t}" for seq, ts, s, t in recent)
                except Exception:
                    pass
                _acquire_api_slot()
                try:
                    ctx = f"\n\n【最近聊天记录】\n{history_text}" if history_text else ""
                    if self.topic:
                        prompt = f"{self.persona}{ctx}\n当前讨论话题：{self.topic}\n请结合上下文主动发表一句关于这个话题的观点。"
                    else:
                        prompt = f"{self.persona}{ctx}\n请结合当前聊天氛围，主动说一句话挑起话题。"
                    result = generate_content(topic=self.topic or "随机话题", preset="custom", api_key=self.api_key,
                                              base_url=self.base_url, model=self.model, custom_prompt=prompt)
                finally:
                    _release_api_slot()
                if result.get("success") and result.get("text"):
                    for line in split_for_minecraft(result["text"]):
                        if self.stop_event.is_set():
                            break
                        self.bot.send_chat(line)
                        time.sleep(1.0)
            except Exception:
                pass

        threading.Thread(target=_talk_worker, daemon=True).start()

    def run(self):
        try:
            self.bot = MCBot(host=self.host, port=self.port, username=self.username,
                             timeout=self.timeout, protocol_version=self.protocol_version)
            self.bot.chat_callback = self._on_chat
            self.bot.connect()
            with self.lock:
                self.status = "connected"
                self.version_name = getattr(self.bot, 'version_name', '') or ""
                self.connect_time = time.time()
            if self.authme_password:
                try:
                    self.bot.authme_login(self.authme_password, register=False)
                except Exception:
                    pass
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
            _log.error(f"[AI Bot {self.username}] run failed: {e}")

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        try:
            if self.bot:
                self.bot.close()
        except Exception:
            pass

    def send_message(self, message):
        if self.bot and self.bot.state == "play":
            for line in split_for_minecraft(message):
                self.bot.send_chat(line)
                time.sleep(0.3)
            return True
        return False

    def get_status(self):
        with self.lock:
            return {
                "session_id": self.session_id, "host": self.host, "port": self.port,
                "username": self.username, "status": self.status, "error": self.error,
                "version": self.version_name,
                "uptime": int(time.time() - self.connect_time) if self.connect_time else 0,
                "chat_count": len(self.chat_log),
            }

    def get_chat(self, since=0):
        with self.lock:
            return [{"seq": s, "time": t, "sender": sd, "text": tx}
                    for s, t, sd, tx in self.chat_log if s > since]


class MultiAIBot:
    """多AI群聊/吵架管理器"""

    def __init__(self):
        self.groups = {}
        self._seq = 0

    def _next_id(self):
        self._seq += 1
        return f"multi_{self._seq}"

    def start_group(self, host, port, bot_count=3, topic="", duration=0,
                    authme_password=None, ai_config=None, persona_indices=None):
        group_id = self._next_id()
        base_config = ai_config or {}
        bots = []
        if persona_indices:
            selected = [PRESET_PERSONAS[i % len(PRESET_PERSONAS)] for i in persona_indices]
        else:
            import random
            selected = random.sample(PRESET_PERSONAS, min(bot_count, len(PRESET_PERSONAS)))
        for i, persona in enumerate(selected[:bot_count]):
            cfg = dict(base_config)
            cfg["persona"] = persona["persona"]
            if topic:
                cfg["persona"] += f"\n当前讨论话题：{topic}。请围绕这个话题和其他玩家讨论。"
            else:
                cfg["persona"] += "\n主动和其他玩家搭话，引发讨论，不要冷场。"
            cfg["reply_cooldown"] = 0.5 + i * 0.3
            cfg["reply_enabled"] = True
            cfg["trigger_keywords"] = []
            cfg["auto_talk_enabled"] = True
            cfg["auto_talk_interval"] = 12.0 + i * 4.0
            cfg["topic"] = topic
            bot = AIBotSession(host=host, port=port, username=persona["name"],
                               authme_password=authme_password, timeout=20.0,
                               duration=duration, ai_config=cfg)
            bot.session_id = f"{group_id}_{i}"
            bot.start()
            bots.append(bot)
            time.sleep(2.0)
        self.groups[group_id] = {"bots": bots, "topic": topic, "host": host, "port": port,
                                 "created_at": datetime.now().isoformat()}

        def _kickoff():
            for _ in range(30):
                if bots and bots[0].bot and getattr(bots[0].bot, "state", None) == "play":
                    break
                time.sleep(1)
            if bots and bots[0].bot and getattr(bots[0].bot, "state", None) == "play":
                opener = topic or "大家觉得这个服务器怎么样？"
                try:
                    bots[0].bot.send_chat(opener)
                    _log.info(f"[MultiAI] opener sent: {opener}")
                except Exception as e:
                    _log.warning(f"[MultiAI] opener failed: {e}")

        threading.Thread(target=_kickoff, daemon=True).start()
        return group_id

    def stop_group(self, group_id):
        if group_id in self.groups:
            for bot in self.groups[group_id]["bots"]:
                bot.stop()
            del self.groups[group_id]
            return True
        return False

    def list_groups(self):
        result = []
        for gid, g in self.groups.items():
            bots_status = [b.get_status() for b in g["bots"]]
            connected = sum(1 for s in bots_status if s["status"] == "connected")
            result.append({"group_id": gid, "host": g["host"], "port": g["port"], "topic": g["topic"],
                           "bot_count": len(g["bots"]), "connected": connected,
                           "created_at": g["created_at"], "bots": bots_status})
        return result

    def get_group_chat(self, group_id, since=0):
        if group_id not in self.groups:
            return []
        all_msgs = []
        for bot in self.groups[group_id]["bots"]:
            all_msgs.extend(bot.get_chat(since))
        all_msgs.sort(key=lambda x: x["seq"])
        return all_msgs

    def send_to_all(self, group_id, message):
        if group_id not in self.groups:
            return False
        for bot in self.groups[group_id]["bots"]:
            try:
                bot.send_message(message)
                time.sleep(0.5)
            except Exception:
                pass
        return True


multi_ai_bot = MultiAIBot()
