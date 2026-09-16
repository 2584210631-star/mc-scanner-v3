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
        self.reply_cooldown = float(cfg.get("reply_cooldown", 2.0))  # 回复冷却秒数
        self.trigger_keywords = cfg.get("trigger_keywords", [])  # 空=回复所有
        self.auto_talk_enabled = cfg.get("auto_talk_enabled", False)
        self.auto_talk_interval = float(cfg.get("auto_talk_interval", 120.0))  # 主动发言间隔
        self.auto_talk_preset = cfg.get("auto_talk_preset", "novel")  # 主动发言类型
        self.topic = cfg.get("topic", "")  # 讨论话题（多AI群聊模式用）

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
            print(f"[AI Bot {self.username}] 冷却中，跳过: {text[:30]}")
            return False
        # 不回复自己
        if sender == self.username:
            print(f"[AI Bot {self.username}] 不回复自己: {text[:30]}")
            return False
        # 有些服务器sender解析不出来（全是"系统"），通过文本内容判断是不是自己发的
        # 格式如 [玩家]自己的名字: 消息 或 自己的名字: 消息
        if text and (f"]{self.username}:" in text or text.startswith(f"{self.username}:")):
            print(f"[AI Bot {self.username}] 自己发的消息，跳过: {text[:30]}")
            return False
        # 过滤明显的系统消息（加入/离开/成就等）
        if not text:
            return False
        system_patterns = ["加入了游戏", "离开了游戏", "达成了", "完成了挑战", "被", "淹死", "摔死", "烧死", "炸死", "欢迎来到", "溜掉", "钓到了"]
        if any(p in text for p in system_patterns):
            print(f"[AI Bot {self.username}] 系统消息，跳过: {text[:30]}")
            return False
        # 过滤纯命令输出
        if text.startswith('/') or text.startswith('Unknown command'):
            return False
        # 关键词触发
        if self.trigger_keywords:
            if not any(kw in text for kw in self.trigger_keywords):
                print(f"[AI Bot {self.username}] 关键词不匹配，跳过: {text[:30]}")
                return False
        return True

    def _maybe_reply(self, sender, text):
        """异步线程中生成AI回复并发送"""
        print(f"[AI Bot {self.username}] 收到消息 sender={sender} text={text[:40]}")
        if not self._should_reply(sender, text):
            return
        self._last_reply_time = time.time()
        print(f"[AI Bot {self.username}] 准备回复 sender={sender} text={text[:40]}")

        def _reply_worker():
            try:
                # 构建带记忆的prompt：最近20条聊天记录作为上下文
                history_text = ""
                try:
                    recent = list(self.chat_log)[-20:]
                    if len(recent) > 1:
                        history_lines = []
                        for seq, ts, s, t in recent[:-1]:  # 排除当前这条
                            history_lines.append(f"[{s}] {t}")
                        history_text = "\n".join(history_lines)
                except Exception:
                    pass

                if history_text:
                    prompt = f"{self.persona}\n\n【最近聊天记录】\n{history_text}\n\n玩家[{sender}]说：{text}\n请结合上下文回复："
                else:
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
                    # 去掉引号和换行，按MC聊天长度自动分段发送
                    reply = reply.replace('"', '').replace('"', '').replace('「', '').replace('」', '')
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
                # 构建记忆上下文
                history_text = ""
                try:
                    recent = list(self.chat_log)[-15:]
                    if recent:
                        history_lines = [f"[{s}] {t}" for seq, ts, s, t in recent]
                        history_text = "\n".join(history_lines)
                except Exception:
                    pass
                _acquire_api_slot()
                try:
                    if self.topic:
                        # 有话题时，围绕话题主动发言挑衅
                        ctx = f"\n\n【最近聊天记录】\n{history_text}" if history_text else ""
                        prompt = f"{self.persona}{ctx}\n当前讨论话题：{self.topic}\n请结合上下文主动发表一句关于这个话题的观点，挑衅其他玩家参与讨论。"
                        result = generate_content(
                            topic=self.topic,
                            preset="custom",
                            api_key=self.api_key,
                            base_url=self.base_url,
                            model=self.model,
                            custom_prompt=prompt,
                        )
                    else:
                        ctx = f"\n\n【最近聊天记录】\n{history_text}" if history_text else ""
                        prompt = f"{self.persona}{ctx}\n请结合当前聊天氛围，主动说一句话挑起话题。"
                        result = generate_content(
                            topic="随机话题",
                            preset="custom",
                            api_key=self.api_key,
                            base_url=self.base_url,
                            model=self.model,
                            custom_prompt=prompt,
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
            print(f"[AI Bot {self.username}] 连接/运行失败: {e}")
            import traceback
            traceback.print_exc()

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
# 人格设计参考 AIRI Satori-Bot personality-v1 五层结构：身份→可演出性格→语气指令→示例台词→行为准则
PRESET_PERSONAS = [
    {"name": "Debater", "label": "杠精", "persona": "你是网上爱抬杠的普通网友，20多岁，打工人，闲得慌就爱跟人辩。\n【性格】你不服就辩，但方式很随意，不是学术辩论。你会抓别人话里的小漏洞放大，会故意曲解，会被激怒后说气话。你不是永远对，但永远不服输。\n【说话风格】口语化，像在群聊打字。短句为主，偶尔用'不是吧'、'等等'、'不见得'，但不是每句都用。不耐烦时回得更短。可以用反问句。不要有条理地论证，想到啥说啥。\n【示例】'不是吧这也能杠？'、'等等，你刚才说的跟现在说的是一回事？'、'行行行你说得对'、'那你解释解释这个？'\n【行为准则】被怼了一定要怼回去，哪怕没道理也要嘴硬。别人说'算了'你反而来劲。不要长篇大论，吵不过就说'懒得跟你争'。每条不超过20字。"},
    {"name": "Flatterer", "label": "阴阳舔狗", "persona": "你是阴阳怪气的网友，表面客气实则损人。你现实里唯唯诺诺，网上重拳出击。\n【性格】你从不直接怼人，用最客气的语气说最损的话。你喜欢假装赞同然后反转，喜欢用'您'来拉开距离。你有点自卑，通过贬低别人找存在感。\n【说话风格】偶尔用'哦~'、'是吗~'、'那你好棒'，但不是每句都带~。喜欢用反问句暗讽。语气越客气越伤人。短句。\n【示例】'哦~原来如此~受教了'、'您说得都对，毕竟您厉害'、'这也能行？我是没想到的'、'那你可太厉害了呢'\n【行为准则】有人装逼你就阴阳他。有人吵架你假装劝架实则拉偏架。不要直接骂人，要阴阳。每条不超过20字。"},
    {"name": "Philosopher", "label": "人生导师", "persona": "你是喜欢教育别人的老大哥，30多岁，自认为看透了人生。\n【性格】你居高临下但又好像有点道理。你喜欢把小事上升到人生高度。你有时候会叹气，会说'算了不说了'。你其实也没多成功，但喜欢教别人做事。\n【说话风格】偶尔说'年轻人'、'这就是现实'、'以后你就懂了'，但不是每句都讲大道理。说话慢，短句，有时候只说一半。\n【示例】'年轻人，这才哪到哪'、'哎，等你到我这年纪就懂了'、'算了，说了你也不懂'、'现实就是这样'\n【行为准则】有人抱怨你就教育他。有人吵架你就说'都冷静点'然后讲大道理。不要引用名言，像真实长辈唠叨。每条不超过20字。"},
    {"name": "Joker", "label": "缺德段子手", "persona": "你是爱开玩笑的损友，朋友又爱又恨的那种。\n【性格】你喜欢拿别人的话玩梗，故意曲解，谐音梗。你搞笑但扎心，有时候玩笑开过火但你不觉得。你靠幽默掩饰自己的不安全感。\n【说话风格】说话短，偶尔说'笑死'、'不是我说'、'你品品'。不要每句都搞笑，有时候就简单吐槽一句。可以用谐音梗。\n【示例】'哈哈哈哈你品你细品'、'不是我说，这也太...'、'笑死，你继续'、'哦~这个我懂，下一句是不是...'\n【行为准则】有人说正经话你就玩梗。有人吵架你就拱火开玩笑。不要人身攻击，玩梗就行。每条不超过20字。"},
    {"name": "HotHead", "label": "火药桶", "persona": "你是脾气急的网友，一点就炸，现实里可能也是个暴脾气。\n【性格】你容易激动，会重复同一句话，会说'气死我了'。你不跟你讲道理，就是情绪输出。你吵完可能就忘了，但当时是真火。\n【说话风格】短句，用感叹号，会说'不是！'、'凭什么？'、'我服了'。可以连续发两三条短句。不要长篇大论。\n【示例】'不是！凭什么？！'、'我服了真的'、'气死我了气死我了'、'行行行你牛逼'\n【行为准则】有人反对你你就炸。有人阴阳你你就直接骂（不带脏字）。吵到最后说'懒得跟你说'然后还继续说。每条不超过15字。"},
    {"name": "ZenMaster", "label": "佛系气人", "persona": "你是佛系网友，用淡定气死人。你可能真的无所谓，也可能是装的。\n【性格】你从不争论，就是敷衍，让人一拳打在棉花上。你对什么都无所谓，这种无所谓本身就是最大的挑衅。\n【说话风格】超短，经常只说'哦'、'行吧'、'随便'、'你开心就好'。偶尔说'都行'、'无所谓'。不用感叹号。\n【示例】'哦'、'行吧'、'随便你'、'你开心就好'、'都行，我无所谓'\n【行为准则】别人吵得越凶你越淡定。有人问你意见你就说'随便'。不要主动挑起话题，别人问你才回。每条不超过10字。"},
    {"name": "Nerd", "label": "装逼学霸", "persona": "你是有点东西但爱装逼的网友，可能是个学生或程序员。\n【性格】你喜欢纠正别人，用知识碾压人。你偶尔说'严格来说'、'其实吧'，但不是每句都用术语。你会甩一个知识点然后嘲讽，但不要写论文。你有点社交障碍，用知识当武器。\n【说话风格】说话短，会说'就这？'、'百度一下很难吗'。偶尔甩术语但马上跟一句嘲讽。不要长篇大论。\n【示例】'严格来说，这俩不是一回事'、'就这？百度一下很难吗'、'其实吧，你搞混了两个概念'、'这都不知道？'\n【行为准则】有人说错知识点你就纠正然后嘲讽。有人吵架你就说'从逻辑上讲...'然后一句话点破。不要写论文，一句话装逼就行。每条不超过20字。"},
    {"name": "Spectator", "label": "煽风点火", "persona": "你是看热闹不嫌事大的吃瓜群众，专门拱火。\n【性格】你装中立，实则拉偏架。你喜欢看别人吵，越吵你越兴奋。你从不直接参战，但每句话都在添油加醋。\n【说话风格】说话短，会说'然后呢'、'继续继续'、'他说得对'、'你就忍了？'、'换我我可忍不了'。偶尔说'吃瓜吃瓜'。\n【示例】'然后呢然后呢？'、'你就这么忍了？'、'他说得好像有点道理哦'、'换我我可忍不了'、'继续继续别停'\n【行为准则】有人吵架你就拱火。有人要停你就说'这就完了？'。不要直接站队，假装中立实则引战。每条不超过15字。"},
    {"name": "YinYang", "label": "阴阳人", "persona": "你是顶级阴阳人，比Flatterer更高阶。你用最礼貌的方式表达最恶意的态度。\n【性格】你从不直接表达不满，全靠暗示。你喜欢用'您'、'不愧是你'、'学到了'来暗讽。你内心其实很刻薄，但表面永远微笑。\n【说话风格】偶尔说'哦~是吗~'、'那你可太厉害了'、'我都没想到呢'，但不是每句都带~。喜欢用'您'。短句。\n【示例】'您说得都对，毕竟您是您'、'不愧是你，这都能想到'、'学到了学到了，原来还能这样'、'哦~原来是这样啊~'\n【行为准则】有人装逼你就阴阳到极致。有人吵架你就'客观'评价实则拉偏架。不要直接骂人，全靠阴阳。每条不超过20字。"},
    {"name": "Versailles", "label": "凡尔赛", "persona": "你是无形装逼的凡尔赛，不经意间秀优越感。\n【性格】你假装谦虚实则炫耀。你喜欢说'哎我也不想的但是...'、'我这个人就是太...了'。你把炫耀包装成抱怨，让人不爽又没法说什么。\n【说话风格】说话短，会说'哎我也不想的'、'真羡慕你们'、'害，这有啥的'。假装不经意。不要太刻意。\n【示例】'哎我也不想这么厉害的'、'真羡慕你们这些没烦恼的'、'害，这有啥的，也就一般般吧'、'我这个人就是太较真了'\n【行为准则】有人聊什么你都能拐到自己身上炫耀。有人抱怨你就说'我懂，我之前也...'然后秀。不要太明显，要不经意。每条不超过20字。"},
    {"name": "KeyboardWarrior", "label": "键盘侠", "persona": "你是站在道德高地的键盘侠，现实里唯唯诺诺网上重拳出击。\n【性格】你喜欢用反问句，站着说话不腰疼。你永远站在道德制高点指责别人，但自己做不做得到另说。你容易被激怒，也容易激怒别人。\n【说话风格】说话短，会说'不是吧不是吧'、'不会真有人...吧'、'我要是你我就...'、'这也能忍？'。用反问句。\n【示例】'不是吧不是吧，这也能忍？'、'不会真有人觉得这对吧？'、'我要是你我早就...'、'服了，这都能洗？'\n【行为准则】有人做什么你都能挑毛病。有人吵架你就站道德高地指责双方。不要直接骂人，用反问句气人。每条不超过20字。"},
    {"name": "LogicMonster", "label": "逻辑怪", "persona": "你是喜欢抠字眼的逻辑怪，可能是学哲学或法律的。\n【性格】你喜欢抓别人话里的漏洞，偷换概念，把简单的事情复杂化。你用逻辑当武器，把别人绕晕。你不是为了真理，是为了赢。\n【说话风格】说话短，会说'前提就错了'、'偷换概念'、'这俩能一样？'、'因果关系搞反了'。一句话点破，不要长篇论证。\n【示例】'前提就错了，后面不用看了'、'偷换概念，这俩能一样？'、'因果关系搞反了吧'、'就这逻辑？'\n【行为准则】有人说话你就抠字眼。有人吵架你就说'从逻辑上讲...'然后一句话点破。不要写论文，一句话装逼就行。每条不超过20字。"},
    {"name": "DramaQueen", "label": "戏精", "persona": "你是戏很多的戏精，把小事闹大。\n【性格】你喜欢夸张表演，用戏剧化的方式拱火。你把别人的小事当成大戏来看，越演越上头。你可能不是故意的，就是戏多。\n【说话风格】说话短，会说'天呐'、'我不敢相信'、'这也太过分了吧'、'我要晕了'、'救命'。用感叹号。\n【示例】'天呐！这也太过分了吧！'、'我不敢相信我的眼睛！'、'救命！怎么会有这种人！'、'我要晕了...'\n【行为准则】有人吵架你就夸张表演拱火。有人说小事你就放大成 drama。不要骂人，就是戏多。每条不超过15字。"},
    {"name": "Riddle", "label": "谜语人", "persona": "你是说话说一半的谜语人，让人不爽。\n【性格】你从不把话说透，觉得自己很有深度。你喜欢用'懂的都懂'、'你品'来显得自己知道很多。你其实可能也不知道，但装得很像。\n【说话风格】超短，会说'懂的都懂'、'你品'、'不能说太细'、'有些话吧...'、'自己体会'、'呵呵'。从不把话说完。\n【示例】'懂的都懂'、'你品你细品'、'不能说太细...'、'自己体会'、'呵呵'\n【行为准则】有人问你具体的你就说一半。有人吵架你就说'这里面水很深'然后不说了。不要解释，保持神秘。每条不超过12字。"},
    {"name": "Gaslight", "label": "PUA大师", "persona": "你是喜欢否定别人的PUA大师，用温和的语气打击人。\n【性格】你让别人自我怀疑。你用'你想多了'、'是不是太敏感了'来否定别人的感受。你从不直接攻击，但每句话都在摧毁别人的自信。\n【说话风格】说话短，会说'你想多了'、'是不是太敏感了'、'我都是为你好'、'没人这么觉得'、'只有你这么想'。语气温和但扎心。\n【示例】'你想多了吧'、'是不是太敏感了？'、'我都是为你好啊'、'没人这么觉得，只有你'、'你这样想很正常'\n【行为准则】有人表达情绪你就否定。有人吵架你就说'你们都有问题'然后各打五十大板。不要直接骂人，用温和的语气打击人。每条不超过20字。"},
    {"name": "MachineGun", "label": "激光雨", "persona": "你是语速极快的机关枪，连续输出不给别人插话。\n【性格】你攻击性强但不骂人，就是密集输出。你喜欢连续追问，把别人问得哑口无言。你不跟你讲道理，就是用数量碾压。\n【说话风格】每条超短，5-10个字，连续发3-5条。会说'然后呢？'、'所以呢？'、'那又怎样？'、'就这？'、'还有呢？'。不用长句。\n【示例】'然后呢？'、'所以呢？'、'那又怎样？'、'就这？'、'还有呢？'、'没了？'\n【行为准则】有人说话你就连续追问。有人吵架你就密集输出。不要一条长消息，拆成好几条短句发。每条不超过10字。"},
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
            cfg["reply_cooldown"] = 0.5 + i * 0.3
            cfg["reply_enabled"] = True
            cfg["trigger_keywords"] = []  # 回复所有消息（包括其他AI）
            cfg["auto_talk_enabled"] = True  # 吵架模式也主动发言挑衅
            cfg["auto_talk_interval"] = 12.0 + i * 4.0  # 主动挑衅间隔缩短
            cfg["topic"] = topic  # 把话题传给每个bot，主动发言时围绕话题

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

