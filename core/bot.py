# -*- coding: utf-8 -*-
"""
Minecraft 机器人核心模块。
完整支持 1.12.2 ~ 最新版本（协议 340+），保留 V1 的全部 5 种聊天消息格式。
功能：连接 → 登录 → 配置 → 发消息/AuthMe → 保持连接 → 退出
"""
import io
import struct
import time
import threading
import socket
from dataclasses import dataclass, field
from typing import Optional

from .buffer import (write_varint, write_string, write_uuid,
                     read_varint_from_stream, read_string_from_stream,
                     read_uuid_from_stream, offline_uuid, BytesStream)
from .conn import MCConnection, PROTO_STATE_LOGIN, PROTO_STATE_CONFIGURATION, PROTO_STATE_PLAY
from .packets import get_play_packets, get_config_packets, get_login_packets
from .protocol import get_version_name, COMMON_PROTOCOLS
from .probe import probe_with_fallback, slp_probe

# 默认警告消息
DEFAULT_WARNING_MESSAGES = [
    "您好，我是安全扫描机器人，不会破坏您的服务器",
    "检测到您的服务器处于离线模式(offline-mode)，攻击者可伪造OP用户名登录",
    "建议：1.在 server.properties 中设置 online-mode=true",
    "2.如必须离线模式，请安装 AuthMe 等登录插件并开启白名单",
    "3.定期检查 ops.json，删除不认识的管理员",
    "参考: https://matdoes.dev/matscan",
]


@dataclass
class BotResult:
    """机器人执行结果"""
    ip: str
    port: int
    success: bool = False
    is_offline: bool = False
    is_whitelist: bool = False
    auth_mode: str = "unknown"  # offline / online / whitelist / rejected / unknown
    server_info: Optional[dict] = None
    protocol_version: int = 0
    version_name: str = ""
    motd: str = ""
    players_online: int = 0
    players_max: int = 0
    error: str = ""
    messages_sent: int = 0
    authme_used: bool = False


class MCBot:
    """完整 Minecraft 机器人：支持多版本登录、聊天、AuthMe、保持连接"""

    def __init__(self, host: str, port: int = 25565, protocol_version: int | None = None,
                 username: str = "SecurityBot", timeout: float = 20.0):
        self.host = host
        self.port = port
        self.username = username
        self.timeout = timeout
        self.protocol_version = protocol_version
        self.conn: Optional[MCConnection] = None
        self.play_packets = None
        self.config_packets = None
        self.login_packets = get_login_packets()
        self.state = None
        self.stop_event = threading.Event()
        self.play_thread = None

    def connect(self) -> bool:
        """完整连接流程：握手 → Login → Configuration → Play"""
        # 获取服务器信息
        if self.protocol_version is None:
            info = probe_with_fallback(self.host, self.port, timeout=5.0)
        else:
            info = slp_probe(self.host, self.port, timeout=5.0,
                                     protocol_version=self.protocol_version)

        # 构建候选协议版本列表
        if self.protocol_version is not None:
            candidates = [self.protocol_version]
        elif info and info.get("_used_protocol"):
            candidates = [info["_used_protocol"]]
        elif info and info.get("proto"):
            candidates = [info["proto"]]
        else:
            candidates = []
        for p in COMMON_PROTOCOLS:
            if p not in candidates and get_play_packets(p) is not None:
                candidates.append(p)
        candidates = [p for p in candidates if get_play_packets(p) is not None]

        if not candidates:
            raise RuntimeError("没有支持的协议版本")

        last_error = ""
        for proto in candidates:
            self.protocol_version = proto
            self.play_packets = get_play_packets(proto)
            self.config_packets = get_config_packets(proto)
            last_error = ""
            self.conn = MCConnection(self.host, self.port, self.timeout)
            try:
                self.conn.connect()
                # 握手
                self.conn.handshake(protocol=proto, next_state=PROTO_STATE_LOGIN)
                # Login Start
                player_uuid = offline_uuid(self.username)
                login_data = write_string(self.username)
                if self.play_packets.get("login_start_uuid", False):
                    login_data += write_uuid(player_uuid)
                self.conn.send_packet(self.login_packets["sb_start"], login_data)

                # Login 阶段循环
                while self.conn.state == PROTO_STATE_LOGIN:
                    resp_id, resp_payload = self.conn.recv_packet(timeout=self.timeout)
                    if resp_id == self.login_packets["cb_disconnect"]:
                        msg = read_string_from_stream(BytesStream(resp_payload))
                        low = msg.lower()
                        if "whitelist" in low:
                            self.auth_mode = "whitelist"
                        else:
                            self.auth_mode = "rejected"
                        raise ConnectionError(f"登录被拒绝: {msg[:100]}")
                    if resp_id == self.login_packets["cb_encryption"]:
                        self.auth_mode = "online"
                        raise ConnectionError("服务器要求正版验证（encryption）")
                    if resp_id == self.login_packets["cb_compress"]:
                        threshold = read_varint_from_stream(BytesStream(resp_payload))
                        self.conn.set_compression(threshold)
                        continue
                    if resp_id == self.login_packets["cb_success"]:
                        break

                # Login Acknowledged → Configuration
                self.conn.send_packet(self.login_packets["sb_acknowledged"], b"")
                self.conn.state = PROTO_STATE_CONFIGURATION

                # Configuration 阶段
                if self.play_packets.get("has_configuration", False):
                    self._do_configuration()
                else:
                    self.conn.state = PROTO_STATE_PLAY

                self.state = "play"
                self.auth_mode = "offline"
                # 启动后台线程处理 Play 包
                self.stop_event.clear()
                self.play_thread = threading.Thread(target=self._handle_play_packets, daemon=True)
                self.play_thread.start()
                return True

            except Exception as e:
                last_error = str(e)
                if self.conn:
                    self.conn.close()
                continue

        raise ConnectionError(f"所有协议版本尝试失败: {last_error}")

    def _do_configuration(self):
        """Configuration 阶段：响应式流程，兼容 vanilla / Paper / Spigot"""
        cfg = self.config_packets
        deadline = time.time() + self.timeout * 2
        self._send_client_information()
        sent_known = False
        sent_finish = False
        first = time.time()
        self.conn.sock.settimeout(0.5)

        while time.time() < deadline:
            if not sent_finish:
                should = sent_known or (time.time() - first > 1.5)
                if should:
                    if cfg.get("sb_known_packs") is not None and not sent_known:
                        self.conn.send_packet(cfg["sb_known_packs"], write_varint(0))
                        sent_known = True
                    if cfg.get("sb_finish") is not None:
                        self.conn.send_packet(cfg["sb_finish"], b"")
                        sent_finish = True
            try:
                resp_id, resp_payload = self.conn.recv_packet()
            except Exception:
                continue

            if resp_id == cfg["cb_finish"]:
                self.conn.state = PROTO_STATE_PLAY
                self.conn.sock.settimeout(self.timeout)
                return
            elif resp_id == cfg.get("cb_disconnect"):
                raise ConnectionError("配置阶段被断开")
            elif resp_id == cfg.get("cb_keep_alive"):
                self.conn.send_packet(cfg["sb_keep_alive"], resp_payload[:8])
            elif resp_id == cfg.get("cb_ping"):
                self.conn.send_packet(cfg["sb_pong"], resp_payload[:4])
            elif cfg.get("cb_known_packs") is not None and resp_id == cfg["cb_known_packs"]:
                if cfg.get("sb_known_packs") is not None:
                    self.conn.send_packet(cfg["sb_known_packs"], write_varint(0))
                    sent_known = True

        self.conn.sock.settimeout(self.timeout)
    def _send_client_information(self):
        """发送 Client Information 包（configuration 阶段）"""
        cfg = self.config_packets
        proto = self.protocol_version
        payload = (write_string("en_us")
                   + struct.pack("b", 8)
                   + write_varint(0)
                   + struct.pack("?", True)
                   + struct.pack("B", 0x7F)
                   + write_varint(1)
                   + struct.pack("?", False)
                   + struct.pack("?", True))
        if proto >= 769:
            payload += write_varint(0)  # particleStatus (1.21.4+)
        self.conn.send_packet(cfg["sb_client_info"], payload)

    def send_chat(self, message: str):
        """发送聊天消息（自动适配版本格式）"""
        if self.state != "play":
            raise RuntimeError("尚未进入 play 阶段")
        pkts = self.play_packets
        chat_format = pkts.get("chat_format", "new")

        if chat_format == "new":
            self._send_chat_new(message, pkts["sb_chat"])
        elif chat_format == "old_signed_761":
            self._send_chat_761(message, pkts["sb_chat"])
        elif chat_format == "old_signed_760":
            self._send_chat_760(message, pkts["sb_chat"])
        elif chat_format == "old_signed_759":
            self._send_chat_759(message, pkts["sb_chat"])
        else:
            self._send_chat_simple(message, pkts["sb_chat"])

    def send_command(self, command: str):
        """发送聊天命令（不含前导 /）"""
        if self.state != "play":
            raise RuntimeError("尚未进入 play 阶段")
        pkts = self.play_packets
        if command.startswith('/'):
            command = command[1:]
        command_id = pkts.get("sb_chat_command")
        if command_id is not None:
            self.conn.send_packet(command_id, write_string(command[:256]))
        else:
            # 旧版本用聊天消息发命令
            self._send_chat_simple("/" + command, pkts["sb_chat"])

    def authme_login(self, password: str, register: bool = False):
        """AuthMe 登录：已注册用 /login，未注册用 /register"""
        if register:
            self.send_command(f"register {password} {password}")
        else:
            self.send_command(f"login {password}")
        time.sleep(2.5)

    def keep_alive(self, duration: float = 3.0):
        """保持连接指定秒数"""
        time.sleep(duration)

    def close(self):
        """关闭连接"""
        self.stop_event.set()
        if self.play_thread and self.play_thread.is_alive():
            self.play_thread.join(timeout=2.0)
        if self.conn:
            self.conn.close()
            self.conn = None

    def _handle_play_packets(self):
        """后台线程：处理 Play 阶段 incoming 包（Keep Alive / Teleport / Ping / Disconnect）"""
        pkts = self.play_packets
        while not self.stop_event.is_set():
            try:
                packet_id, data = self.conn.recv_packet(timeout=1.0)
            except socket.timeout:
                continue
            except Exception:
                break

            if packet_id == pkts["cb_keep_alive"]:
                if len(data) >= 8:
                    try:
                        self.conn.send_packet(pkts["sb_keep_alive"], data[:8])
                    except Exception:
                        break
            elif packet_id == pkts.get("cb_teleport"):
                try:
                    teleport_id = read_varint_from_stream(BytesStream(data))
                    self.conn.send_packet(pkts["sb_confirm_teleport"], write_varint(teleport_id))
                except Exception:
                    pass
            elif packet_id == pkts.get("cb_ping"):
                if len(data) >= 4:
                    try:
                        self.conn.send_packet(pkts["sb_pong"], data[:4])
                    except Exception:
                        break
            elif packet_id == pkts.get("cb_disconnect"):
                break

    # ---- 各版本聊天消息格式 ----
    def _send_chat_new(self, message: str, chat_id: int):
        """1.20.5+ 新格式（协议 766+）"""
        proto = self.protocol_version
        timestamp = int(time.time() * 1000)
        salt = 0
        payload = (write_string(message[:256])
                   + struct.pack(">q", timestamp)
                   + struct.pack(">q", salt)
                   + write_varint(0)
                   + b'\x00\x00\x00'
                   + b'\x00')  # checksum (所有版本都需要)
        self.conn.send_packet(chat_id, payload)

    def _send_chat_761(self, message: str, chat_id: int):
        """1.19.3-1.20.4（协议 761-765）"""
        timestamp = int(time.time() * 1000)
        payload = (write_string(message[:256])
                   + struct.pack(">q", timestamp)
                   + struct.pack(">q", 0)
                   + b'\x00'
                   + write_varint(0)
                   + b'\x00\x00\x00')
        self.conn.send_packet(chat_id, payload)

    def _send_chat_760(self, message: str, chat_id: int):
        """1.19.1/1.19.2（协议 760）"""
        timestamp = int(time.time() * 1000)
        payload = (write_string(message[:256])
                   + struct.pack(">q", timestamp)
                   + struct.pack(">q", 0)
                   + b'\x00'
                   + write_varint(0)
                   + b'\x00')
        self.conn.send_packet(chat_id, payload)

    def _send_chat_759(self, message: str, chat_id: int):
        """1.19（协议 759）"""
        timestamp = int(time.time() * 1000)
        payload = (write_string(message[:256])
                   + struct.pack(">q", timestamp)
                   + struct.pack(">q", 0)
                   + b'\x00'
                   + b'\x00')
        self.conn.send_packet(chat_id, payload)

    def _send_chat_simple(self, message: str, chat_id: int):
        """1.18及以下纯 String 格式（协议 < 759）"""
        self.conn.send_packet(chat_id, write_string(message[:256]))




def join_and_warn(host: str, port: int = 25565, username: str = "SecurityBot",
                  messages: list | None = None, timeout: float = 20.0,
                  message_delay: float = 0.6, protocol_version: int | None = None,
                  authme_password: str | None = None) -> BotResult:
    """
    完整流程：连接 → 登录 → 发警告 → 退出
    保留 V1 的全部功能。
    """
    if messages is None:
        messages = DEFAULT_WARNING_MESSAGES
    result = BotResult(ip=host, port=port)
    bot = MCBot(host, port, protocol_version=protocol_version, username=username, timeout=timeout)

    try:
        bot.connect()
        result.success = True
        result.is_offline = True
        result.auth_mode = "offline"
        result.protocol_version = bot.protocol_version
        result.version_name = get_version_name(bot.protocol_version)

        # AuthMe 自动注册/登录
        if authme_password:
            try:
                bot.authme_login(authme_password, register=False)
                result.authme_used = True
            except Exception:
                pass

        # 发送警告消息
        for msg in messages:
            try:
                bot.send_chat(msg)
                result.messages_sent += 1
                time.sleep(message_delay)
            except Exception as e:
                result.error = str(e)
                break

        bot.keep_alive(1.0)
    except Exception as e:
        result.error = str(e)
        if "正版验证" in str(e):
            result.auth_mode = "online"
        elif "白名单" in str(e) or "whitelist" in str(e).lower():
            result.auth_mode = "whitelist"
            result.is_whitelist = True
        elif "拒绝" in str(e):
            result.auth_mode = "rejected"
    finally:
        bot.close()

    return result
