# -*- coding: utf-8 -*-
import os
import json
import time
import threading
import traceback
from datetime import datetime
from collections import deque
from core.bot import MCBot


class ObserverSession:
    """单个服务器观察者会话"""
    def __init__(self, host, port, username, authme_password=None, timeout=20.0, duration=0, protocol_version=None):
        self.session_id = ""
        self.duration = duration  # 观察时长（秒），0=一直观察
        self.host = host
        self.port = port
        self.username = username
        self.authme_password = authme_password
        self.timeout = timeout
        self.protocol_version = protocol_version
        self.bot = None
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.status = "connecting"  # connecting / connected / disconnected / stopped / error
        self.error = ""
        self.auth_mode = "unknown"
        self.version_name = ""
        self.start_time = time.time()
        self.connect_time = None
        self.disconnect_time = None
        self.chat_log = deque(maxlen=1000)   # (seq, time_str, text)
        self.events = deque(maxlen=2000)     # (seq, time_str, type, text)  type: chat/join/leave
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
                self.events.append((self._next_seq(), self._ts(), "chat", sender, text))
                self.chat_log.append((self._seq, self._ts(), sender, text))
        except Exception:
            pass

    def _on_player(self, name, action):
        try:
            with self.lock:
                self.events.append((self._next_seq(), self._ts(), action, name))
        except Exception:
            pass

    def run(self):
        try:
            self.bot = MCBot(host=self.host, port=self.port,
                             username=self.username, timeout=self.timeout,
                             protocol_version=self.protocol_version)
            self.bot.chat_callback = self._on_chat
            self.bot.player_callback = self._on_player
            self.bot.connect()
            with self.lock:
                self.status = "connected"
                self.auth_mode = self.bot.auth_mode
                self.version_name = get_version_name(self.bot.protocol_version)
                self.protocol_version = self.bot.protocol_version
                self.connect_time = time.time()
            if self.authme_password:
                try:
                    self.bot.authme_login(self.authme_password, register=False)
                except Exception:
                    pass
            # 保持连接：直到手动停止、观察时长到期或服务器断开
            while not self.stop_event.is_set():
                if not getattr(self.bot, "connected", True):
                    with self.lock:
                        self.status = "disconnected"
                        self.disconnect_time = time.time()
                    return
                if self.duration > 0 and (time.time() - self.connect_time) >= self.duration:
                    with self.lock:
                        self.status = "stopped"
                        self.disconnect_time = time.time()
                    return
                time.sleep(0.5)
            with self.lock:
                self.status = "stopped"
                self.disconnect_time = time.time()
        except Exception as e:
            with self.lock:
                self.status = "error"
                self.error = str(e)[:300]
            print(f"[观察者错误] {self.username}@{self.host}:{self.port} - {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.bot:
                try:
                    self.bot.close()
                except Exception:
                    pass
            # 会话结束前保存聊天记录到文件，被ban/踢后仍可导出
            try:
                os.makedirs('observer_logs', exist_ok=True)
                safe_id = self.session_id.replace('/', '_').replace('\\', '_')
                with open(f'observer_logs/{safe_id}.json', 'w', encoding='utf-8') as f:
                    json.dump({
                        'session_id': self.session_id,
                        'host': self.host, 'port': self.port,
                        'username': self.username,
                        'status': self.status,
                        'chat_log': list(self.chat_log),
                        'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }, f, ensure_ascii=False)
            except Exception:
                pass
            # 会话结束后从全局字典移除，防止内存泄漏
            try:
                with observer_lock:
                    observer_sessions.pop(self.session_id, None)
            except Exception:
                pass

    def stop(self):
        self.stop_event.set()

    def _players(self):
        if not self.bot:
            return []
        try:
            return sorted(set(v for v in self.bot.player_list.values() if v))
        except Exception:
            return []

    def brief(self):
        with self.lock:
            return {
                "session_id": self.session_id,
                "host": self.host,
                "port": self.port,
                "username": self.username,
                "status": self.status,
                "error": self.error,
                "auth_mode": self.auth_mode,
                "version_name": self.version_name,
                "uptime": time.time() - self.start_time,
                "players_online": len(self._players()),
                "chat_count": len(self.chat_log),
            }

    def full(self, since=None):
        with self.lock:
            players = self._players()
            all_events = list(self.events)
            last_seq = self._seq
        if since is not None:
            all_events = [e for e in all_events if e[0] > since]
        # events: chat=(seq,time,type,sender,text)  join/leave=(seq,time,type,name)
        events_out = []
        for e in all_events[-100:]:
            if e[2] == "chat":
                events_out.append({"seq": e[0], "time": e[1], "type": e[2], "sender": e[3], "text": e[4]})
            else:
                events_out.append({"seq": e[0], "time": e[1], "type": e[2], "name": e[3]})
        return {
            "session_id": self.session_id,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "status": self.status,
            "error": self.error,
            "auth_mode": self.auth_mode,
            "version_name": self.version_name,
            "protocol_version": self.protocol_version,
            "start_time": self.start_time,
            "connect_time": self.connect_time,
            "uptime": time.time() - self.start_time,
            "players_online": len(players),
            "players": players,
            "events": events_out,
            "last_seq": last_seq,
            "chat": list(self.chat_log),
        }

