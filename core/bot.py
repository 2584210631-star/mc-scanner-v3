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
                     read_uuid_from_stream, read_boolean_from_stream,
                     offline_uuid, BytesStream)
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
    modded_channels: set = field(default_factory=set)  # 握手期间发现的插件频道（模组服特征）


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
        self.connected = False  # 是否仍处于 play 阶段（观察者依赖此判断掉线）
        self.player_list = {}  # uuid -> name
        self.player_callback = None  # callable(name: str, action: str) -> None  action: join/leave
        # 模组服握手期间观察到的插件频道（Forge/Fabric 等）
        self.modded_channels = set()
        # 聊天消息监听（用于插件抓取等）
        self.chat_messages: list[str] = []
        self._chat_lock = threading.Lock()
        self.chat_callback = None  # callable(text: str, sender: str) -> None

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
                    if resp_id == self.login_packets.get("cb_plugin_request"):
                        # 模组服（Forge FML2/FML3、Fabric 等）在登录阶段发送插件请求。
                        # vanilla 客户端对所有未知频道一律回复 declined，服务端 vanilla 验收后放行。
                        self._handle_login_plugin_request(resp_payload)
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
                self.connected = True
                return True

            except Exception as e:
                last_error = str(e)
                if self.conn:
                    self.conn.close()
                continue

        raise ConnectionError(f"所有协议版本尝试失败: {last_error}")

    def _handle_login_plugin_request(self, payload: bytes):
        """响应登录阶段插件消息（LoginPluginRequest → LoginPluginResponse）。

        模组服（Forge 1.13~1.20.1 的 fml:loginwrapper / fml:login、
        NeoForge、部分 Fabric）会在登录阶段发送插件请求。
        vanilla 客户端对未知频道一律回复 declined（successful=false + 空载荷），
        Forge 的 "Vanilla acceptance test" 通过后即放行；若不回复，服务端会一直等待导致进不去。
        """
        from .buffer import read_varint, read_string
        try:
            msg_id, off = read_varint(payload, 0)
            channel, _ = read_string(payload, off)
        except Exception:
            channel = ""
        if channel:
            self.modded_channels.add(channel)
        try:
            # LoginPluginResponse: MessageID(VarInt) + Successful(Boolean=false)
            self.conn.send_packet(self.login_packets["sb_plugin_response"],
                                  write_varint(msg_id) + b"\x00")
        except Exception:
            pass

    def _do_configuration(self):
        """Configuration 阶段：响应式流程，兼容 vanilla / Paper / Spigot / Velocity"""
        cfg = self.config_packets
        deadline = time.time() + max(self.timeout, 8.0)
        self._send_client_information()
        self._send_brand()
        sent_known = False
        sent_finish = False
        first = time.time()
        self.conn.sock.settimeout(0.3)

        while time.time() < deadline:
            if not sent_finish:
                # 1.5秒后或收到KnownPacks后发送finish，给服务器足够时间发配置数据
                should = sent_known or (time.time() - first > 1.5)
                if should:
                    if cfg.get("sb_known_packs") is not None and not sent_known:
                        self.conn.send_packet(cfg["sb_known_packs"], write_varint(0))
                        sent_known = True
                    if cfg.get("sb_finish") is not None:
                        self.conn.send_packet(cfg["sb_finish"], b"")
                        sent_finish = True
                        finish_time = time.time()
            try:
                resp_id, resp_payload = self.conn.recv_packet()
            except Exception:
                # 发送finish后2秒仍未收到cb_finish，强行进入Play（兼容Velocity/Bungee）
                if sent_finish and (time.time() - finish_time > 2.0):
                    self.conn.state = PROTO_STATE_PLAY
                    self.conn.sock.settimeout(self.timeout)
                    return
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
            elif cfg.get("cb_plugin_message") is not None and resp_id == cfg["cb_plugin_message"]:
                self._handle_config_plugin_message(resp_payload)
            elif cfg.get("cb_known_packs") is not None and resp_id == cfg["cb_known_packs"]:
                if cfg.get("sb_known_packs") is not None:
                    self.conn.send_packet(cfg["sb_known_packs"], write_varint(0))
                    sent_known = True

        # 超时后强行进入Play（兼容不发finish的代理服）
        self.conn.state = PROTO_STATE_PLAY
        self.conn.sock.settimeout(self.timeout)

    def _handle_config_plugin_message(self, payload: bytes):
        """处理配置阶段插件消息（Custom Payload）。

        - minecraft:brand：回送客户端品牌（vanilla），部分服务端会等待
        - fabric:negotiate：Fabric 1.20.2+ 配置协商任务，回同频道空载荷（尽力而为）
        - fml:handshake / fml:play 等：vanilla 客户端直接忽略，Forge vanilla 验收放行
        """
        cfg = self.config_packets
        from .buffer import read_string
        try:
            channel, off = read_string(payload, 0)
        except Exception:
            channel = ""
        self.modded_channels.add(channel)
        if channel in ("minecraft:brand", "MC|Brand"):
            try:
                self.conn.send_packet(cfg["sb_plugin_message"],
                                      write_string("minecraft:brand") + write_string("vanilla"))
            except Exception:
                pass
        elif channel == "fabric:negotiate":
            # Fabric 配置协商：回复同频道空数据，表示“无 Fabric 模组”，多数服放行
            try:
                self.conn.send_packet(cfg["sb_plugin_message"],
                                      write_string("fabric:negotiate") + b"")
            except Exception:
                pass
        # fml:handshake 等其余频道保持静默（与 vanilla 客户端行为一致）
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

    def _send_brand(self):
        """发送客户端品牌（vanilla）。部分服务端（模组服/反作弊）会等待品牌包。"""
        cfg = self.config_packets
        if not cfg or cfg.get("sb_plugin_message") is None:
            return
        try:
            self.conn.send_packet(cfg["sb_plugin_message"],
                                  write_string("minecraft:brand") + write_string("vanilla"))
        except Exception:
            pass

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

    def authme_login(self, password: str, register: bool = False, auto_register: bool = True):
        """AuthMe 登录：已注册用 /login，未注册自动 /register"""
        if register:
            self.send_command(f"register {password} {password}")
        else:
            self.send_command(f"login {password}")
            if auto_register:
                time.sleep(1.5)
                self.send_command(f"register {password} {password}")
        time.sleep(2.0)

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
        """后台线程：处理 Play 阶段 incoming 包（Keep Alive / Teleport / Ping / Disconnect）。
        观察者依赖本循环维护：聊天抓取(chat_callback)、玩家进出(player_callback)、连接状态(connected)。"""
        pkts = self.play_packets
        try:
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
                elif packet_id == pkts.get("cb_player_info"):
                    # Player Info Update — 解析玩家列表
                    try:
                        stream = BytesStream(data)
                        actions = read_varint_from_stream(stream)
                        count = read_varint_from_stream(stream)
                        for _ in range(count):
                            try:
                                uid = str(read_uuid_from_stream(stream))
                                if actions & 0x01:  # ADD_PLAYER
                                    name = read_string_from_stream(stream)
                                    is_new = uid not in self.player_list
                                    self.player_list[uid] = name
                                    props = read_varint_from_stream(stream)
                                    for _ in range(props):
                                        read_string_from_stream(stream); read_string_from_stream(stream)
                                        if read_boolean_from_stream(stream): read_string_from_stream(stream)
                                    if is_new and self.player_callback:
                                        try:
                                            self.player_callback(name, "join")
                                        except Exception:
                                            pass
                                if self.protocol_version >= 761:
                                    # 1.19.3+ 动作位：add(0x01) init_chat(0x02) gamemode(0x04)
                                    # listed(0x08) latency(0x10) display(0x20)；移除走独立 cb_player_remove 包
                                    if actions & 0x02:  # initialize_chat — chat session
                                        if read_boolean_from_stream(stream):
                                            stream.read(16)  # uuid
                                            stream.read(8)   # expireTime
                                            klen = read_varint_from_stream(stream)
                                            stream.read(klen)
                                    if actions & 0x04: read_varint_from_stream(stream)  # update_game_mode
                                    if actions & 0x08: read_varint_from_stream(stream)  # update_listed
                                    if actions & 0x10: read_varint_from_stream(stream)  # update_latency
                                    if actions & 0x20:
                                        if read_boolean_from_stream(stream): read_string_from_stream(stream)  # display name
                                else:
                                    # 旧版(<761, 1.19.2前) 动作位：add(0x01) gamemode(0x02)
                                    # latency(0x04) display(0x08) remove(0x10)
                                    if actions & 0x02: read_varint_from_stream(stream)  # gamemode
                                    if actions & 0x04: read_varint_from_stream(stream)  # latency
                                    if actions & 0x08:
                                        if read_boolean_from_stream(stream): read_string_from_stream(stream)  # display name
                                    if actions & 0x10:  # REMOVE_PLAYER
                                        old = self.player_list.pop(uid, None)
                                        if old is not None and self.player_callback:
                                            try:
                                                self.player_callback(old, "leave")
                                            except Exception:
                                                pass
                            except Exception:
                                break
                    except Exception:
                        pass
                elif packet_id == pkts.get("cb_player_remove"):
                    # 1.19.3+ 独立玩家移除包：UUID 数组
                    try:
                        stream = BytesStream(data)
                        count = read_varint_from_stream(stream)
                        for _ in range(count):
                            try:
                                uid = str(read_uuid_from_stream(stream))
                                old = self.player_list.pop(uid, None)
                                if old is not None and self.player_callback:
                                    try:
                                        self.player_callback(old, "leave")
                                    except Exception:
                                        pass
                            except Exception:
                                break
                    except Exception:
                        pass
                elif packet_id == pkts.get("cb_chat_message") or packet_id == pkts.get("cb_system_chat") or packet_id == pkts.get("cb_profileless_chat"):
                    # 聊天消息 — 提取文本用于插件抓取/命令响应
                    try:
                        is_system = (packet_id == pkts.get("cb_system_chat")) or (packet_id == pkts.get("cb_profileless_chat"))
                        text, sender = self._extract_chat_with_sender(data, is_system)
                        if text:
                            with self._chat_lock:
                                self.chat_messages.append(text)
                            if self.chat_callback:
                                try:
                                    self.chat_callback(text, sender)
                                except Exception:
                                    pass
                    except Exception:
                        pass
        finally:
            # 循环退出（掉线/被断开/停止）即视为连接结束，观察者据此判断
            self.connected = False

    def _extract_chat_with_sender(self, data: bytes, is_system: bool):
        """从聊天包提取 (text, sender)，sender 为玩家名或'系统'"""
        import json
        sender = "系统"
        try:
            stream = BytesStream(data)
            if not is_system:
                if self.protocol_version >= 761:
                    # 1.19.3+: senderUuid(16) + index + signature + message
                    uuid_bytes = stream.read(16)
                    import uuid as _uuid
                    uuid_str = str(_uuid.UUID(bytes=uuid_bytes))
                    sender = self.player_list.get(uuid_str, "未知玩家")
                else:
                    # 旧版: UUID(16) + nickname(JSON String) + ...
                    stream.read(16)
                    nick_json = read_string_from_stream(stream)
                    try:
                        sender = self._json_component_to_text(json.loads(nick_json))
                    except Exception:
                        sender = nick_json
        except Exception:
            pass
        text = self._extract_chat_text(data, is_system)
        return text, sender

    def _extract_chat_text(self, data: bytes, is_system: bool) -> str:
        """从聊天包 payload 中提取纯文本（简化版，尽力解析 JSON 组件）"""
        import json
        try:
            stream = BytesStream(data)
            if is_system:
                # System Chat: 1.20.5+ 内容为 network NBT 聊天组件；
                # 旧版本为 JSON String + VarInt(type)
                if self.protocol_version >= 766:
                    # 用 NBT 解析（content 为匿名 NBT 文本组件）
                    try:
                        txt = self._nbt_component_to_text(stream)
                        if txt:
                            return txt
                    except Exception:
                        pass
                json_str = read_string_from_stream(stream)
            elif self.protocol_version >= 761:
                # Player Chat (1.19.3+): senderUuid(16) + index(VarInt)
                # + has_signature(Boolean) + signature(256 if true) + message(JSON String) + ...
                stream.read(16)  # senderUuid
                read_varint_from_stream(stream)  # index
                if read_boolean_from_stream(stream):  # signature option
                    stream.read(256)  # signature
                json_str = read_string_from_stream(stream)  # plainMessage
            else:
                # Player Chat (旧版 1.19.2 前): UUID(16) + nickname(JSON String)
                # + timestamp(8) + salt(8) + has_signature(Boolean)
                # + signature(256 if true) + message(JSON String) + ...
                stream.read(16)  # UUID
                read_string_from_stream(stream)  # nickname
                stream.read(8)  # timestamp
                stream.read(8)  # salt
                has_sig = read_boolean_from_stream(stream)
                if has_sig:
                    stream.read(256)  # signature
                json_str = read_string_from_stream(stream)
            # 解析 JSON 组件提取文本
            try:
                obj = json.loads(json_str)
                return self._json_component_to_text(obj)
            except (json.JSONDecodeError, TypeError):
                return json_str  # 可能是纯文本
        except Exception:
            return ""

    @staticmethod
    def _json_component_to_text(obj) -> str:
        """将 Minecraft JSON 聊天组件转为纯文本"""
        import json
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            parts = []
            if obj.get("text"):
                parts.append(str(obj["text"]))
            if obj.get("translate"):
                parts.append(str(obj["translate"]))
            extra = obj.get("extra")
            if isinstance(extra, list):
                for e in extra:
                    parts.append(MCBot._json_component_to_text(e))
            return "".join(parts)
        if isinstance(obj, list):
            return "".join(MCBot._json_component_to_text(e) for e in obj)
        return str(obj) if obj else ""

    # ---- 1.20.5+ system chat 使用 network NBT 编码的聊天组件 ----
    @staticmethod
    def _nbt_read_string(stream) -> str:
        """network NBT 字符串：2 字节大端长度 + UTF-8"""
        raw = stream.read(2)
        if len(raw) < 2:
            return ""
        slen = int.from_bytes(raw, "big")
        return stream.read(slen).decode("utf-8", "ignore")

    @staticmethod
    def _nbt_skip_value(stream, tag: int):
        """跳过未知 NBT 值"""
        if tag == 0x01:  # byte
            stream.read(1)
        elif tag == 0x02:  # short
            stream.read(2)
        elif tag in (0x03, 0x05, 0x06):  # int / float / double
            stream.read(4) if tag in (0x03, 0x05) else stream.read(8)
        elif tag == 0x04:  # long
            stream.read(8)
        elif tag == 0x07:  # byte array
            stream.read(int.from_bytes(stream.read(4), "big"))
        elif tag == 0x08:  # string
            MCBot._nbt_read_string(stream)
        elif tag == 0x09:  # list
            elem = stream.read(1)
            if not elem:
                return
            count = int.from_bytes(stream.read(4), "big")
            for _ in range(count):
                MCBot._nbt_skip_value(stream, elem[0])
        elif tag == 0x0a:  # compound
            MCBot._nbt_compound_to_text(stream)
        elif tag == 0x0b:  # int array
            stream.read(4 * int.from_bytes(stream.read(4), "big"))
        elif tag == 0x0c:  # long array
            stream.read(8 * int.from_bytes(stream.read(4), "big"))

    @staticmethod
    def _nbt_compound_to_text(stream) -> str:
        """解析 network NBT 聊天组件（TAG_Compound），提取可读文本"""
        text_val = ""
        translate_key = ""
        with_parts = []
        extra_parts = []
        while True:
            raw = stream.read(1)
            if not raw:
                break
            tag = raw[0]
            if tag == 0x00:  # TAG_End
                break
            name = MCBot._nbt_read_string(stream)
            if tag == 0x08:  # TAG_String
                val = MCBot._nbt_read_string(stream)
                if name == "text":
                    text_val = val
                elif name == "translate":
                    translate_key = val
            elif tag == 0x09:  # TAG_List（with / extra）
                elem_type_raw = stream.read(1)
                if not elem_type_raw:
                    break
                elem_type = elem_type_raw[0]
                count = int.from_bytes(stream.read(4), "big")
                items = []
                for _ in range(count):
                    if elem_type == 0x0a:
                        items.append(MCBot._nbt_compound_to_text(stream))
                    elif elem_type == 0x08:
                        items.append(MCBot._nbt_read_string(stream))
                    else:
                        MCBot._nbt_skip_value(stream, elem_type)
                if name == "with":
                    with_parts = items
                elif name == "extra":
                    extra_parts = items
            elif tag == 0x0a:  # 嵌套 compound（hoverEvent 等，跳过）
                MCBot._nbt_compound_to_text(stream)
            else:
                MCBot._nbt_skip_value(stream, tag)
        # translate 常见键的友好翻译
        _TRANSLATE = {
            # 玩家进出
            "multiplayer.player.joined": "加入了游戏",
            "multiplayer.player.left": "离开了游戏",
            "multiplayer.player.list": "玩家列表",
            # 聊天类型
            "chat.type.text": "",
            "chat.type.emote": "",
            "chat.type.announcement": "[公告]",
            "chat.type.admin": "[管理员]",
            # 成就/进度
            "chat.type.advancement.task": "达成了进度",
            "chat.type.advancement.goal": "达成了目标",
            "chat.type.advancement.challenge": "完成了挑战",
            # 命令反馈
            "commands.op.success": "已被设置为管理员",
            "commands.deop.success": "已被移出管理员",
            "commands.ban.success": "已被封禁",
            "commands.pardon.success": "已被解封",
            "commands.kick.success": "已被踢出",
            "commands.whitelist.add.success": "已加入白名单",
            "commands.whitelist.remove.success": "已移出白名单",
            "commands.gamemode.success.self": "游戏模式已更新",
            "commands.gamemode.success.other": "的游戏模式已更新",
            "commands.stop.start": "服务器正在关闭...",
            "commands.teleport.success": "已传送",
            "commands.give.success": "已给予物品",
            "commands.clear.success": "已清除物品",
            "commands.effect.success": "已添加效果",
            "commands.effect.clear.everything": "已清除所有效果",
            "commands.say": "",
            "commands.me": "",
            "commands.help.header": "--- 帮助 ---",
            # 死亡消息
            "death.attack.generic": "死了",
            "death.attack.player": "被杀死了",
            "death.attack.mob": "被怪物杀死了",
            "death.attack.fall": "摔死了",
            "death.attack.drown": "淹死了",
            "death.attack.lava": "被岩浆烧死了",
            "death.attack.fire": "被烧死了",
            "death.attack.explosion": "被炸死了",
            "death.attack.void": "掉入虚空",
            "death.attack.outOfWorld": "掉出了世界",
            "death.attack.magic": "被魔法杀死了",
            "death.attack.wither": "被凋零效果杀死了",
            "death.attack.starve": "饿死了",
            "death.attack.anvil": "被铁砧砸死了",
            "death.attack.cactus": "被仙人掌扎死了",
            "death.attack.dragonBreath": "被龙息杀死了",
            # 系统
            "multiplayer.gameMode.changed": "游戏模式已更改",
            "multiplayer.disconnect.generic": "连接断开",
            "multiplayer.disconnect.kicked": "被踢出",
            "multiplayer.disconnect.banned": "被封禁",
            "multiplayer.disconnect.whitelisted": "不在白名单中",
            "multiplayer.disconnect.serverFull": "服务器已满",
            "multiplayer.disconnect.outdatedServer": "服务器版本过旧",
            "multiplayer.disconnect.outdatedClient": "客户端版本过旧",
        }
        if translate_key:
            friendly = _TRANSLATE.get(translate_key)
            # 成就类消息：with = [玩家名, 成就名]，格式化为 "玩家名 达成了目标 [成就名]"
            if translate_key.startswith("chat.type.advancement") and len(with_parts) >= 2:
                player = with_parts[0]
                adv = with_parts[1]
                if friendly:
                    return f"{player} {friendly} [{adv}]"
                return f"{player} {translate_key} [{adv}]"
            prefix = "".join(with_parts)
            if friendly is not None:
                return prefix + (" " + friendly if friendly else "")
            return prefix + " " + translate_key
        return text_val + "".join(extra_parts)

    @staticmethod
    def _nbt_component_to_text(stream) -> str:
        """解析 network NBT 聊天组件（根节点可能为 Compound 或 String）"""
        raw = stream.read(1)
        if not raw:
            return ""
        tag = raw[0]
        if tag == 0x0a:  # TAG_Compound
            return MCBot._nbt_compound_to_text(stream)
        if tag == 0x08:  # TAG_String（纯文本组件）
            return MCBot._nbt_read_string(stream)
        if tag == 0x00:  # TAG_End
            return ""
        MCBot._nbt_skip_value(stream, tag)
        return ""

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
                   + write_varint(0))
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
        result.modded_channels = set(bot.modded_channels)

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
