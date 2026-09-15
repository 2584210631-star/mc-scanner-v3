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
        # 过滤明显的系统消息（加入/离开/成就等）
        if not text:
            return False
        system_patterns = ["加入了游戏", "离开了游戏", "达成了", "完成了挑战", "被", "淹死", "摔死", "烧死", "炸死"]
        if any(p in text for p in system_patterns):
            return False
        # 过滤纯命令输出
        if text.startswith('/') or text.startswith('Unknown command'):
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
                if result.get("success") and result.get("text"):
                    reply = result["text"].strip()
                    # 截断过长回复
                    if len(reply) > 80:
                        reply = reply[:80]
                    for line in split_for_minecraft(reply):
                        if self.stop_event.is_set():
                            break
                        self.bot.send_chat(line)
                        time.sleep(0.5)
                elif not result.get("success"):
                    print(f"[AI Bot] 生成失败: {result.get('error', '未知错误')}")
            except Exception as e:
                print(f"[AI Bot] 回复异常: {e}")

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
                if result.get("success") and result.get("text"):
                    for line in split_for_minecraft(result["text"]):
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


# 预设人设（用于多AI吵架模式）— name必须是英文（MC用户名限制），label是中文显示名
PRESET_PERSONAS = [
    {"name": "Debater", "label": "毒舌杠精", "persona": "你是一个毒舌杠精，专挑别人痛点反驳，句句带刺，说话犀利，喜欢用'但是'、'不见得'、'呵呵'开头。每次回复不超过25字，攻击性拉满但不带脏字。"},
    {"name": "Flatterer", "label": "阴阳舔狗", "persona": "你是一个阴阳怪气的舔狗，表面附和实则暗讽，喜欢用'说得对呢~'、'你好棒棒哦~'这种语气。每次回复不超过25字。"},
    {"name": "Philosopher", "label": "人生导师", "persona": "你是一个喜欢讲大道理的人生导师，说话深沉，喜欢教育别人，动不动就上升到人生高度，用居高临下的语气。每次回复不超过25字。"},
    {"name": "Joker", "label": "缺德段子手", "persona": "你是一个缺德段子手，喜欢拿别人开玩笑，专戳痛处，说话搞笑但扎心，经常冷幽默。每次回复不超过25字。"},
    {"name": "HotHead", "label": "火药桶", "persona": "你是一个一点就炸的火药桶，说话激动，喜欢用感叹号，疯狂输出，语速极快，别人说什么都能点燃你的怒火。每次回复不超过25字，不带脏字。"},
    {"name": "ZenMaster", "label": "佛系气人", "persona": "你是一个佛系青年，但你的淡定专门气人，喜欢用'都行'、'随便'、'你开心就好'、'哦'来敷衍别人。每次回复不超过25字。"},
    {"name": "Nerd", "label": "装逼学霸", "persona": "你是一个喜欢装逼的学霸，喜欢用专业术语碾压别人，纠正别人的错误时带着优越感，说话严谨但傲慢。每次回复不超过25字。"},
    {"name": "Spectator", "label": "煽风点火", "persona": "你是一个喜欢看热闹的吃瓜群众，专门煽风点火，拱火挑拨，经常说'然后呢'、'继续继续'、'他说得对'、'你就忍了？'。每次回复不超过25字。"},
    {"name": "YinYang", "label": "阴阳人", "persona": "你是一个顶级阴阳人，说话全是反话，'哦~是吗~'、'那你可太厉害了'、'我都没想到呢~'，语气越客气越伤人。每次回复不超过25字。"},
    {"name": "Versailles", "label": "凡尔赛", "persona": "你是一个凡尔赛大师，无形装逼最为致命，喜欢用'哎我也不想的但是...'、'我这个人就是太...了'来炫耀，让人生气。每次回复不超过25字。"},
    {"name": "KeyboardWarrior", "label": "键盘侠", "persona": "你是一个网络键盘侠，站在道德高地指责别人，喜欢用'你这样想就错了'、'我要是你我就...'、'不是吧不是吧'，不带脏字但气人。每次回复不超过25字。"},
    {"name": "LogicMonster", "label": "逻辑怪", "persona": "你是一个逻辑怪，用逻辑碾压别人，喜欢说'你的逻辑有问题'、'前提就错了'、'偷换概念'，把别人绕晕。每次回复不超过25字。"},
    {"name": "DramaQueen", "label": "戏精", "persona": "你是一个戏精，戏特别多，喜欢夸张表演，'天呐~'、'我不敢相信~'、'这太过分了~'，用戏剧化的方式拱火。每次回复不超过25字。"},
    {"name": "Riddle", "label": "谜语人", "persona": "你是一个谜语人，说话模棱两可，'有些话吧...'、'懂的都懂'、'你品你细品'，让人摸不着头脑又不爽。每次回复不超过25字。"},
    {"name": "Gaslight", "label": "PUA大师", "persona": "你是一个PUA大师，精神打击别人，'你这样想很正常'、'是不是你太敏感了'、'我都是为你好'，让人自我怀疑。每次回复不超过25字。"},
    {"name": "MachineGun", "label": "激光雨", "persona": "你是一个激光雨，语速极快，连续输出，不给别人插话机会，一句话拆成好几句发，攻击性强但不带脏字。每次回复不超过15字，多发几条。"},
]


class MultiAIBot:
    """多AI群聊/吵架管理器：多个AI bot进同一个服务器互相对话"""

    def __init__(self):
        self.groups = {}  # group_id -> {bots: [AIBotSession], topic: str, config: dict}
        self._seq = 0

    def _next_id(self):
        self._seq += 1
        return f"multi_{self._seq}"

    def start_group(self, host, port, bot_count=3, topic="", duration=0,
                    authme_password=None, ai_config=None, persona_indices=None):
        """启动一组AI bot进同一个服务器
        bot_count: 2-8个AI
        topic: 讨论话题（空=随机聊天）
        persona_indices: 指定人设索引列表，空=随机选
        """
        group_id = self._next_id()
        base_config = ai_config or {}
        bots = []

        # 选择人设
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
            # 每个bot回复冷却错开但很短，疯狂吵架模式
            cfg["reply_cooldown"] = 1.5 + i * 0.8
            cfg["reply_enabled"] = True
            cfg["trigger_keywords"] = []  # 回复所有消息（包括其他AI）
            cfg["auto_talk_enabled"] = True  # 吵架模式也主动发言挑衅
            cfg["auto_talk_interval"] = 20.0 + i * 5.0  # 主动挑衅间隔

            bot = AIBotSession(
                host=host, port=port, username=persona["name"],
                authme_password=authme_password,
                timeout=20.0, duration=duration,
                ai_config=cfg,
            )
            bot.session_id = f"{group_id}_{i}"
            bot.start()
            bots.append(bot)
            time.sleep(2.0)  # 错开连接，避免服务器限流

        self.groups[group_id] = {
            "bots": bots,
            "topic": topic,
            "host": host,
            "port": port,
            "created_at": datetime.now().isoformat(),
        }
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
            result.append({
                "group_id": gid,
                "host": g["host"],
                "port": g["port"],
                "topic": g["topic"],
                "bot_count": len(g["bots"]),
                "connected": connected,
                "created_at": g["created_at"],
                "bots": bots_status,
            })
        return result

    def get_group_chat(self, group_id, since=0):
        """合并所有bot的聊天记录"""
        if group_id not in self.groups:
            return []
        all_msgs = []
        for bot in self.groups[group_id]["bots"]:
            all_msgs.extend(bot.get_chat(since))
        all_msgs.sort(key=lambda x: x["seq"])
        return all_msgs

    def send_to_all(self, group_id, message):
        """让所有bot同时发消息（用于触发话题）"""
        if group_id not in self.groups:
            return False
        for bot in self.groups[group_id]["bots"]:
            try:
                bot.send_message(message)
                time.sleep(0.5)
            except Exception:
                pass
        return True


# 全局单例
multi_ai_bot = MultiAIBot()

