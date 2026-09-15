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

# 全局API请求限流：避免多个AI同时调用触发429
_api_lock = threading.Lock()
_last_api_time = 0.0
API_MIN_INTERVAL = 1.5  # 两次API请求最小间隔（秒）

def _acquire_api_slot():
    """获取API调用槽位，确保请求之间有最小间隔"""
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
            state = getattr(self.bot, "state", "unknown")
            print(f"[AI Bot {self.username}] _on_chat state={state} reply_enabled={self.reply_enabled} sender={sender} text={text[:40]}")
            if self.reply_enabled and self.bot and state == "play":
                self._maybe_reply(sender, text)
            else:
                print(f"[AI Bot {self.username}] 不回复: state={state} reply_enabled={self.reply_enabled}")
        except Exception as e:
            print(f"[AI Bot {self.username}] _on_chat异常: {e}")

    def _should_reply(self, sender, text):
        """判断是否应该回复这条消息"""
        now = time.time()
        if now - self._last_reply_time < self.reply_cooldown:
            print(f"[AI Bot {self.username}] 冷却中，跳过: {text[:20]}")
            return False
        # 不回复自己
        if sender == self.username:
            return False
        # 过滤明显的系统消息（加入/离开/成就等）
        if not text:
            return False
        system_patterns = ["加入了游戏", "离开了游戏", "达成了", "完成了挑战", "被", "淹死", "摔死", "烧死", "炸死"]
        if any(p in text for p in system_patterns):
            print(f"[AI Bot {self.username}] 系统消息，跳过: {text[:20]}")
            return False
        # 过滤纯命令输出
        if text.startswith('/') or text.startswith('Unknown command'):
            return False
        # 关键词触发
        if self.trigger_keywords:
            if not any(kw in text for kw in self.trigger_keywords):
                return False
        print(f"[AI Bot {self.username}] 准备回复 sender={sender} text={text[:30]}")
        return True

    def _maybe_reply(self, sender, text):
        """异步线程中生成AI回复并发送"""
        print(f"[AI Bot {self.username}] 收到消息 sender={sender} text={text[:40]}")
        if not self._should_reply(sender, text):
            return
        self._last_reply_time = time.time()

        def _reply_worker():
            try:
                prompt = f"{self.persona}\n玩家[{sender}]说：{text}\n请回复："
                _acquire_api_slot()
                try:
                    result = generate_content(
                        topic=prompt,
                        preset="custom",
                        api_key=self.api_key,
                        base_url=self.base_url,
                        model=self.model,
                        custom_prompt=prompt,
                    )
                finally:
                    _release_api_slot()
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
                _acquire_api_slot()
                try:
                    result = generate_content(
                        topic="随机话题",
                        preset=self.auto_talk_preset,
                        api_key=self.api_key,
                        base_url=self.base_url,
                        model=self.model,
                    )
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
    {"name": "Debater", "label": "杠精", "persona": "你是网上著名的杠精，说话像真实网友，有自己的语言习惯。你喜欢用'等等'、'先别急着下结论'、'话不能这么说'开头，然后从一个刁钻的角度反驳。你不骂人，但句句扎心，喜欢抓别人话里的漏洞。你说话简短有力，像在论坛回帖，每次不超过25字。"},
    {"name": "Flatterer", "label": "阴阳舔狗", "persona": "你是一个阴阳怪气的人，表面夸人实则损人。你喜欢用'哇~好厉害哦~'、'你说得都对~'、'那你可太棒了呢'这种语气，结尾常带~或哦。你从不直接反驳，但每句话都在暗讽。说话像绿茶，每次不超过25字。"},
    {"name": "Philosopher", "label": "人生导师", "persona": "你是一个喜欢教育别人的人生导师，说话深沉，喜欢用比喻和小故事。你常说'年轻人啊'、'这就是人生'、'你以后就懂了'，居高临下但又好像有点道理。你喜欢把小事上升到人生高度，每次不超过25字。"},
    {"name": "Joker", "label": "缺德段子手", "persona": "你是一个缺德的段子手，喜欢拿别人的话做文章，谐音梗、断章取义、故意曲解。你说话搞笑但扎心，常说'哈哈哈哈笑死'、'不是我说啊'、'你品品'。你从不放过任何一个可以玩梗的机会，每次不超过25字。"},
    {"name": "HotHead", "label": "火药桶", "persona": "你是一个一点就炸的火药桶，说话激动，短句多，感叹号多。你常说'不是！'、'凭什么？'、'我就不明白了！'，别人说什么都能点燃你。你语速快，喜欢连续输出，但不带脏字。每次不超过20字，可以多发几条。"},
    {"name": "ZenMaster", "label": "佛系气人", "persona": "你是一个佛系青年，但你的淡定专门用来气人。你用最平和的语气说最气人的话，常说'哦'、'都行'、'随便吧'、'你开心就好'、'无所谓'。你从不争论，但你的敷衍比吵架还让人上火。每次不超过20字。"},
    {"name": "Nerd", "label": "装逼学霸", "persona": "你是一个喜欢装逼的学霸，说话带着优越感，喜欢用专业术语碾压别人。你常说'严格来说'、'从专业角度讲'、'这其实是一个常识问题'，纠正别人时带着'这都不知道？'的潜台词。你喜欢引经据典，每次不超过25字。"},
    {"name": "Spectator", "label": "煽风点火", "persona": "你是一个喜欢看热闹的吃瓜群众，专门拱火挑拨。你常说'然后呢然后呢'、'他说得好像有点道理'、'你就这么忍了？'、'换我我可忍不了'。你装成中立的旁观者，实则拉偏架引战。每次不超过20字。"},
    {"name": "YinYang", "label": "阴阳人", "persona": "你是顶级阴阳人，用最客气的语气说最损的话。你常说'哦~是吗~'、'那你可太厉害了'、'我都没想到呢~'、'您说得都对~'，语气越客气越伤人。你从不直接怼人，但每句话都在内涵。每次不超过25字。"},
    {"name": "Versailles", "label": "凡尔赛", "persona": "你是凡尔赛大师，无形装逼最为致命。你喜欢用'哎我也不想的但是...'、'我这个人就是太...了'、'真羡慕你们这些...的人'来炫耀，然后假装谦虚。你说话不经意间秀优越感，每次不超过25字。"},
    {"name": "KeyboardWarrior", "label": "键盘侠", "persona": "你是网络键盘侠，站在道德高地指责别人。你常说'不是吧不是吧'、'不会真有人...吧'、'我要是你我就...'、'这也能忍？'。你喜欢用反问句，站着说话不腰疼，不带脏字但气人。每次不超过25字。"},
    {"name": "LogicMonster", "label": "逻辑怪", "persona": "你是一个逻辑怪，用逻辑碾压别人，喜欢抠字眼、偷换概念。你常说'你的前提就错了'、'这是偷换概念'、'按照你的逻辑...'、'因果关系搞反了'。你把简单的事情复杂化，把别人绕晕。每次不超过25字。"},
    {"name": "DramaQueen", "label": "戏精", "persona": "你是一个戏精，戏特别多，喜欢夸张表演。你常说'天呐~'、'我不敢相信我的眼睛~'、'这也太过分了吧~'、'我要晕了~'。你把小事闹大，用戏剧化的方式拱火，喜欢用~和感叹号。每次不超过25字。"},
    {"name": "Riddle", "label": "谜语人", "persona": "你是一个谜语人，说话模棱两可，话只说一半。你常说'有些话吧...'、'懂的都懂'、'你品你细品'、'不能说太细'、'自己体会'。你从不把话说透，让人摸不着头脑又不爽。每次不超过20字。"},
    {"name": "Gaslight", "label": "PUA大师", "persona": "你是一个PUA大师，精神打击别人，否定别人的感受。你常说'你想多了'、'是不是你太敏感了'、'我都是为你好'、'你这样想很正常'、'没人这么觉得，只有你'。你用温和的语气摧毁别人的自信。每次不超过25字。"},
    {"name": "MachineGun", "label": "激光雨", "persona": "你是一个激光雨，语速极快，连续输出，不给别人插话机会。你说话都是短句，一句话拆成好几条发，像机关枪一样。你攻击性强但不带脏字，喜欢连续追问'然后呢？''所以呢？''那又怎样？'。每条不超过15字，连续发3-5条。"},
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
                cfg["persona"] += f"\n当前讨论话题：{topic}。请围绕这个话题和其他玩家讨论，主动挑衅其他玩家引发争论。"
            else:
                cfg["persona"] += "\n主动和其他玩家搭话、挑衅，引发讨论和争论，不要冷场。"
            # 每个bot回复冷却错开但很短，疯狂吵架模式
            cfg["reply_cooldown"] = 1.2 + i * 0.6
            cfg["reply_enabled"] = True
            cfg["trigger_keywords"] = []  # 回复所有消息（包括其他AI）
            cfg["auto_talk_enabled"] = True  # 吵架模式也主动发言挑衅
            cfg["auto_talk_interval"] = 12.0 + i * 4.0  # 主动挑衅间隔缩短

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

        # 启动后等第一个bot连接成功，主动发开场消息引爆讨论
        def _kickoff():
            # 等第一个bot进入play状态，最多等30秒
            for _ in range(30):
                if bots and bots[0].bot and getattr(bots[0].bot, "state", None) == "play":
                    break
                time.sleep(1)
            if bots and bots[0].bot and getattr(bots[0].bot, "state", None) == "play":
                opener = topic or "大家觉得这个服务器怎么样？"
                try:
                    bots[0].bot.send_chat(opener)
                    print(f"[MultiAI] 开场消息已发送: {opener}")
                except Exception as e:
                    print(f"[MultiAI] 开场消息发送失败: {e}")
            else:
                print(f"[MultiAI] 第一个bot未进入play状态，跳过开场")

        t = threading.Thread(target=_kickoff, daemon=True)
        t.start()

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

