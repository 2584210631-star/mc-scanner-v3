# -*- coding: utf-8 -*-
"""
Minecraft 机器人核心模块。
完整支持 1.12.2 ~ 最新版本（协议 340+），保留 V1 的全部 5 种聊天消息格式。
功能：连接 → 登录 → 配置 → 发消息/AuthMe → 保持连接 → 退出
"""
import struct
import time
import threading
import socket
import os
from dataclasses import dataclass, field
from typing import Optional

from . import nbt as _nbt
from . import chat as _chat

# 正版调试开关：默认关闭，设环境变量 MC_DEBUG=1 开启
_DEBUG = os.environ.get("MC_DEBUG", "") == "1"

def _dprint(msg):
    """正版调试输出，默认关闭"""
    if _DEBUG:
        print(msg)

from .buffer import (write_varint, write_string, read_varint_from_stream,
                     read_string_from_stream, read_uuid_from_stream,
                     offline_uuid, BytesStream)
from .conn import MCConnection, PROTO_STATE_LOGIN, PROTO_STATE_CONFIGURATION, PROTO_STATE_PLAY
from .packets import get_play_packets, get_config_packets, get_login_packets
from .protocol import get_version_name, COMMON_PROTOCOLS
from .probe import probe_with_fallback

# 默认警告消息
DEFAULT_WARNING_MESSAGES = [
    "您好，我是安全扫描机器人，不会破坏您的服务器",
    "检测到您的服务器处于离线模式(offline-mode)，攻击者可伪造OP用户名登录",
    "建议：1.在 server.properties 中设置 online-mode=true",
    "2.如必须离线模式，请安装 AuthMe 等登录插件并开启白名单",
    "3.定期检查 ops.json，删除不认识的管理员",
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

    # 聊天翻译键 → 中文友好文本（JSON 和 NBT 组件共用，定义在 core/nbt.py）
    _TRANSLATE_MAP = _nbt.TRANSLATE_MAP

    def __init__(self, host: str, port: int = 25565, protocol_version: int | None = None,
                 username: str = "SecurityBot", timeout: float = 20.0, use_premium: bool = True):
        self.host = host
        self.port = port
        self.username = username
        self.timeout = timeout
        self.protocol_version = protocol_version
        self.use_premium = use_premium  # 是否允许使用正版账户登录
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
        # 聊天消息监听（用于插件抓取等）；有界：防长时运行无界增长
        self.chat_messages: list[str] = []
        self.MAX_CHAT_MESSAGES = 2000
        self._chat_lock = threading.Lock()
        self.chat_callback = None  # callable(text: str, sender: str) -> None
        self.protocol_handler = None  # 版本协议处理器，按版本模块化
        # 正版认证
        self.msa_token = None
        self.msa_uuid = None
        self._refresh_token = None
        # 当前位置（用于定期发送位置更新，防止服务器超时断开）
        self._pos_x = 0.0
        self._pos_y = 0.0
        self._pos_z = 0.0
        self._pos_yaw = 0.0
        self._pos_pitch = 0.0
        self._last_pos_update = 0.0
        self._has_position = False  # 收到teleport后才发送位置更新，避免位置全0导致服务器异常
        # 创建时自动加载正版token（这样观察者列表能直接显示正版用户名）
        if self.use_premium:
            try:
                import config as _cfg
                # 优先从多账户列表加载当前活跃账户
                _accounts = _cfg.get("msa_accounts", []) or []
                _active_uuid = _cfg.get("msa_active_uuid", "") or ""
                _token = None
                _uuid = None
                _name = None
                if _accounts:
                    if _active_uuid:
                        for _a in _accounts:
                            if _a.get("uuid") == _active_uuid:
                                _token = _a.get("access_token")
                                _uuid = _a.get("uuid")
                                _name = _a.get("name")
                                self._refresh_token = _a.get("refresh_token", "")
                                break
                    if not _token:
                        _token = _accounts[0].get("access_token")
                        _uuid = _accounts[0].get("uuid")
                        _name = _accounts[0].get("name")
                        self._refresh_token = _accounts[0].get("refresh_token", "")
                # 兼容旧字段（优先mc_，兜底msa_）
                if not _token:
                    _token = _cfg.get("mc_access_token", "") or _cfg.get("msa_access_token", "") or None
                    _uuid = _cfg.get("mc_uuid", "") or _cfg.get("msa_uuid", "") or None
                    _name = _cfg.get("mc_name", "") or _cfg.get("msa_name", "")
                if _token and _uuid:
                    self.msa_token = _token
                    self.msa_uuid = _uuid
                    if _name:
                        self.username = _name
                        print(f"[MCBot] 自动使用正版账号: {_name}")
            except Exception as e:
                print(f"[MCBot] 加载正版token失败: {e}")

    def connect(self) -> bool:
        """完整连接流程：握手 → Login → Configuration → Play"""
        # 自动加载正版token（仅当use_premium为True时）
        if self.use_premium:
            try:
                import config as _cfg
                if not self.msa_token:
                    _accounts = _cfg.get("msa_accounts", []) or []
                    _active_uuid = _cfg.get("msa_active_uuid", "") or ""
                    if _accounts:
                        if _active_uuid:
                            for _a in _accounts:
                                if _a.get("uuid") == _active_uuid:
                                    self.msa_token = _a.get("access_token")
                                    self.msa_uuid = _a.get("uuid")
                                    self.username = _a.get("name", self.username)
                                    self._refresh_token = _a.get("refresh_token", "")
                                    break
                        if not self.msa_token:
                            self.msa_token = _accounts[0].get("access_token")
                            self.msa_uuid = _accounts[0].get("uuid")
                            self.username = _accounts[0].get("name", self.username)
                            self._refresh_token = _accounts[0].get("refresh_token", "")
                    if not self.msa_token:
                        self.msa_token = _cfg.get("mc_access_token", "") or _cfg.get("msa_access_token", "") or None
                        self.msa_uuid = _cfg.get("mc_uuid", "") or _cfg.get("msa_uuid", "") or None
                if self.msa_token and self.msa_uuid and not self.username:
                    self.username = _cfg.get("mc_name", "") or _cfg.get("msa_name", self.username)
            except Exception:
                pass
        # 获取服务器信息（protocol_version已知时跳过探测，直接握手，避免重复连接）
        if self.protocol_version is None:
            info = probe_with_fallback(self.host, self.port, timeout=5.0)
        else:
            info = None  # 已知协议版本，跳过SLP探测

        # 构建候选协议版本列表
        if self.protocol_version is not None:
            candidates = [int(self.protocol_version)]
        elif info and info.get("_used_protocol"):
            candidates = [int(info["_used_protocol"])]
        elif info and info.get("proto"):
            candidates = [int(info["proto"])]
        else:
            candidates = []
        for p in COMMON_PROTOCOLS:
            if p not in candidates and get_play_packets(p) is not None:
                candidates.append(p)
        candidates = [p for p in candidates if get_play_packets(p) is not None]

        if not candidates:
            raise RuntimeError("没有支持的协议版本")

        last_error = ""
        _requested_proto = self.protocol_version  # 保存用户初始指定的协议号，循环中会被覆盖
        _throttle_retries = {}
        _idx = 0
        while _idx < len(candidates):
            proto = candidates[_idx]
            self.protocol_version = proto
            self.play_packets = get_play_packets(proto)
            self.config_packets = get_config_packets(proto)
            from .protocols import get_protocol_handler
            self.protocol_handler = get_protocol_handler(self)
            last_error = ""
            self.conn = MCConnection(self.host, self.port, self.timeout)
            try:
                self.conn.connect()
                # 握手
                self.conn.handshake(protocol=proto, next_state=PROTO_STATE_LOGIN)
                # Login Start — 由版本协议处理器构造
                player_uuid = offline_uuid(self.username)
                self.uuid = player_uuid  # 保存自己的UUID，用于聊天发送者识别
                login_data = self.protocol_handler.login_start_payload(self.username, player_uuid)
                self.conn.send_packet(self.login_packets["sb_start"], login_data)

                # Login 阶段循环
                while self.conn.state == PROTO_STATE_LOGIN:
                    resp_id, resp_payload = self.conn.recv_packet(timeout=self.timeout)
                    if self.msa_token:
                        _dprint(f"[正版调试] 收到Login包: id=0x{resp_id:02x}, payload_len={len(resp_payload)}")
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
                        if not self.msa_token:
                            raise ConnectionError("服务器要求正版验证，但未登录正版账号")
                        # 解析encryption request
                        s = BytesStream(resp_payload)
                        server_id = read_string_from_stream(s)
                        pubkey_len = read_varint_from_stream(s)
                        pubkey_bytes = s.read(pubkey_len)
                        vtoken_len = read_varint_from_stream(s)
                        vtoken = s.read(vtoken_len)
                        _dprint(f"[正版调试] 收到Encryption Request: server_id={server_id!r}, pubkey_len={pubkey_len}, vtoken_len={vtoken_len}")
                        # 生成shared secret
                        import os as _os
                        shared_secret = _os.urandom(16)
                        _dprint(f"[正版调试] 生成shared_secret: {shared_secret.hex()[:16]}...")
                        # RSA加密（优先pycryptodome，备选pyjnius/APK）
                        enc_secret = None
                        enc_vtoken = None
                        # 优先pycryptodome（Termux/桌面环境）
                        try:
                            from Crypto.Cipher import PKCS1_v1_5
                            from Crypto.PublicKey import RSA
                            pub_key = RSA.import_key(pubkey_bytes)
                            cipher = PKCS1_v1_5.new(pub_key)
                            enc_secret = cipher.encrypt(shared_secret)
                            enc_vtoken = cipher.encrypt(vtoken)
                            _dprint(f"[正版调试] RSA加密成功(pycryptodome): enc_secret_len={len(enc_secret)}, enc_vtoken_len={len(enc_vtoken)}")
                        except ImportError:
                            pass
                        # 备选pyjnius（APK环境，调用Java Cipher）
                        if enc_secret is None:
                            try:
                                from jnius import autoclass
                                KeyFactory = autoclass('java.security.KeyFactory')
                                X509EncodedKeySpec = autoclass('java.security.spec.X509EncodedKeySpec')
                                Cipher = autoclass('javax.crypto.Cipher')
                                keySpec = X509EncodedKeySpec(pubkey_bytes)
                                kf = KeyFactory.getInstance("RSA")
                                pubKey = kf.generatePublic(keySpec)
                                cipher = Cipher.getInstance("RSA/ECB/PKCS1Padding")
                                cipher.init(Cipher.ENCRYPT_MODE, pubKey)
                                enc_secret = bytes(cipher.doFinal(shared_secret))
                                enc_vtoken = bytes(cipher.doFinal(vtoken))
                                _dprint(f"[正版调试] RSA加密成功(pyjnius): enc_secret_len={len(enc_secret)}, enc_vtoken_len={len(enc_vtoken)}")
                            except ImportError:
                                raise RuntimeError("当前环境不支持正版服加密，请安装pycryptodome（pip install pycryptodome）或使用APK")
                        # 计算server ID hash（Java风格有符号十六进制，和Minecraft服务器一致）
                        import hashlib as _hl
                        _hash_bytes = _hl.sha1(server_id.encode() + shared_secret + pubkey_bytes).digest()
                        _bigint = int.from_bytes(_hash_bytes, 'big', signed=True)
                        sid_hash = ('-' + format(-_bigint, 'x')) if _bigint < 0 else format(_bigint, 'x')
                        _dprint(f"[正版调试] server_id_hash={sid_hash}")
                        # 向Mojang join（selectedProfile必须是不带横线的32字符UUID）
                        from .microsoft_auth import join_server, refresh_mc_token
                        _uuid_no_dash = self.msa_uuid.replace('-', '') if self.msa_uuid else ''
                        _join_ok = join_server(self.msa_token, _uuid_no_dash, sid_hash)
                        _dprint(f"[正版调试] join_server返回: {_join_ok}, uuid={_uuid_no_dash}")
                        if not _join_ok and self._refresh_token:
                            # token可能过期，尝试自动刷新
                            print("[正版] joinServer失败，尝试自动刷新token...")
                            _refreshed = refresh_mc_token(self._refresh_token)
                            if _refreshed and _refreshed.get("access_token"):
                                self.msa_token = _refreshed["access_token"]
                                self._refresh_token = _refreshed.get("refresh_token", self._refresh_token)
                                # 更新配置中的token
                                try:
                                    import config as _cfg
                                    _accounts = _cfg.get("msa_accounts", []) or []
                                    for _a in _accounts:
                                        if _a.get("uuid") == self.msa_uuid:
                                            _a["access_token"] = self.msa_token
                                            _a["refresh_token"] = self._refresh_token
                                            break
                                    _cfg.set("msa_accounts", _accounts)
                                    _cfg.set("mc_access_token", self.msa_token)
                                    _cfg.save_config()
                                except Exception:
                                    pass
                                _join_ok = join_server(self.msa_token, _uuid_no_dash, sid_hash)
                                print(f"[正版] 刷新后joinServer: {'成功' if _join_ok else '失败'}")
                        if not _join_ok:
                            raise ConnectionError("正版joinServer验证失败")
                        # 发送encryption response（注意：长度必须用VarInt，不能用1字节，RSA加密后256字节会溢出）
                        from .buffer import write_varint
                        resp = b""
                        resp += write_varint(len(enc_secret))
                        resp += enc_secret
                        resp += write_varint(len(enc_vtoken))
                        resp += enc_vtoken
                        _dprint(f"[正版调试] 发送Encryption Response: 总长度={len(resp)}")
                        self.conn.send_packet(0x01, resp)
                        # 启用AES加密
                        self.conn.enable_encryption(shared_secret)
                        _dprint(f"[正版调试] AES加密已启用: backend={self.conn._crypto_backend}")
                        continue
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
                        _dprint(f"[正版调试] 收到Login Success! payload_len={len(resp_payload)}")
                        # 解析服务器返回的真实UUID（离线服可能与offline_uuid不同）
                        try:
                            ss = BytesStream(resp_payload)
                            real_uuid = read_uuid_from_stream(ss)
                            if real_uuid:
                                self.uuid = real_uuid
                                _dprint(f"[正版调试] 服务器返回UUID: {real_uuid}")
                        except Exception as _e:
                            _dprint(f"[正版调试] 解析UUID失败: {_e}")
                        break

                # Configuration 阶段（仅 1.20.2+ 需要 Login Acknowledged）
                if self.play_packets.get("has_configuration", False):
                    self.conn.send_packet(self.login_packets["sb_acknowledged"], b"")
                    self.conn.state = PROTO_STATE_CONFIGURATION
                    self._do_configuration()
                else:
                    self.conn.state = PROTO_STATE_PLAY

                self.state = "play"
                self.auth_mode = "offline"
                # Play阶段初始化：发送Client Settings和Player Position（旧版本服务器需要，否则可能超时断开）
                self._send_play_client_settings()
                self._send_play_player()
                # 启动后台线程处理 Play 包
                self.stop_event.clear()
                self.play_thread = threading.Thread(target=self._handle_play_packets, daemon=True)
                self.play_thread.start()
                self.connected = True
                return True

            except Exception as e:
                last_error = f"proto={proto}: {e}"
                if self.conn:
                    self.conn.close()
                # 连接节流时等4秒重试当前协议（最多3次）
                if "throttled" in str(e).lower():
                    _throttle_retries[proto] = _throttle_retries.get(proto, 0) + 1
                    if _throttle_retries[proto] < 3:
                        time.sleep(4.0)
                        continue  # 不递增索引，重试当前协议
                # 用户指定协议后，失败不继续试其他版本（尊重用户选择）
                if _requested_proto is not None:
                    break
                # SLP探测到协议后，incompatible（版本不兼容）说明探测版本不对，继续试；其他错误break
                if info and (info.get("_used_protocol") or info.get("proto")):
                    is_incompatible = "incompatible" in str(last_error).lower()
                    if not is_incompatible:
                        break
                _idx += 1

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
        """Configuration 阶段：等服务器发 Finish Configuration 后回应，兼容 vanilla / Paper / Spigot / Velocity"""
        cfg = self.config_packets
        _dprint(f"[Config调试] 进入Configuration阶段")
        deadline = time.time() + max(self.timeout, 15.0)
        self._send_client_information()
        self._send_brand()
        _dprint(f"[Config调试] 已发送Client Information和Brand")
        sent_known = False
        sent_finish = False
        _cfg_packet_count = 0

        while time.time() < deadline:
            try:
                resp_id, resp_payload = self.conn.recv_packet(timeout=0.5)
                _cfg_packet_count += 1
                _dprint(f"[Config调试] 收到包: id=0x{resp_id:02x}, len={len(resp_payload)}")
            except ConnectionError:
                # 连接已断开：立即失败，避免在已关闭连接上空转忙循环
                _dprint(f"[Config调试] 连接已断开")
                raise
            except Exception:
                # 超时兜底：某些旧服务器/代理不主动发Finish，超时后才主动发
                if not sent_finish and time.time() > deadline - 1.0 and cfg.get("sb_finish") is not None:
                    try:
                        self.conn.send_packet(cfg["sb_finish"], b"")
                        sent_finish = True
                        _dprint(f"[Config调试] 超时主动发送Finish")
                    except Exception:
                        pass
                continue

            if resp_id == cfg["cb_finish"]:
                # 服务器发 Finish Configuration，客户端回复后进入 Play
                _dprint(f"[Config调试] 收到Finish Configuration，回复并进入Play")
                if cfg.get("sb_finish") is not None and not sent_finish:
                    try:
                        self.conn.send_packet(cfg["sb_finish"], b"")
                    except Exception:
                        pass
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
                if cfg.get("sb_known_packs") is not None and not sent_known:
                    self.conn.send_packet(cfg["sb_known_packs"], write_varint(0))
                    sent_known = True
                # 注意：不在这里发Finish！Paper 1.20.2+有配置任务队列，必须等服务器发cb_finish
            elif cfg.get("cb_cookie_request") is not None and resp_id == cfg["cb_cookie_request"]:
                try:
                    _stream = BytesStream(resp_payload)
                    _key = read_string_from_stream(_stream)
                    if cfg.get("sb_cookie_response") is not None:
                        self.conn.send_packet(cfg["sb_cookie_response"],
                                              write_string(_key) + b"\x00")
                except Exception:
                    pass

        # 超时后强行进入Play（兼容不发finish的代理服）
        _dprint(f"[Config调试] 超时未收到Finish，强行进入Play（共收到{_cfg_packet_count}个配置包）")
        self.conn.state = PROTO_STATE_PLAY
        if self.conn.sock is not None:
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
        payload = (write_string("en_us")
                   + struct.pack("b", 8)
                   + write_varint(0)
                   + struct.pack("?", True)
                   + struct.pack("B", 0x7F)
                   + write_varint(1)
                   + struct.pack("?", False)
                   + struct.pack("?", True))
        payload += self.protocol_handler.get_client_info_extra()
        self.conn.send_packet(cfg["sb_client_info"], payload)

    def _send_play_client_settings(self):
        """旧版本（<1.20.2）在Play阶段发送Client Settings。
        1.12.2等服务器需要收到设置包后才允许聊天。"""
        pkts = self.play_packets
        if not pkts or pkts.get("sb_client_info") is None:
            return
        try:
            payload = (write_string("zh_CN")
                       + struct.pack("b", 8)       # viewDistance
                       + write_varint(0)           # chatMode: 0=enabled
                       + struct.pack("?", True)    # chatColors
                       + struct.pack("B", 0x7F)    # displayedSkinParts
                       + write_varint(1))          # mainHand: 1=right
            self.conn.send_packet(pkts["sb_client_info"], payload)
        except Exception:
            pass

    def _send_play_player(self):
        """旧版本在Play阶段发送Player（flying）包，告诉服务器玩家已就绪在地面上。
        不发这个包，1.12.2 Vanilla可能认为玩家还在加载中，拒绝聊天消息。"""
        pkts = self.play_packets
        if not pkts or pkts.get("sb_player_flying") is None:
            return
        try:
            self.conn.send_packet(pkts["sb_player_flying"], b'\x01')  # onGround=True
        except Exception:
            pass

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
        chat_id = pkts["sb_chat"]
        payload = self.protocol_handler.send_chat_payload(message)
        self.conn.send_packet(chat_id, payload)

    def send_command(self, command: str):
        """发送聊天命令（不含前导 /）"""
        if self.state != "play":
            raise RuntimeError("尚未进入 play 阶段")
        pkts = self.play_packets
        if command.startswith('/'):
            command = command[1:]
        command_id = pkts.get("sb_chat_command")
        if command_id is not None:
            payload = self.protocol_handler.send_command_payload(command)
            self.conn.send_packet(command_id, payload)
        else:
            self.send_chat("/" + command[:255])

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
        _dprint(f"[Play调试] Play线程启动, keep_alive_cb=0x{pkts.get('cb_keep_alive', 0):02x}")
        _packet_count = 0
        try:
            while not self.stop_event.is_set():
                try:
                    packet_id, data = self.conn.recv_packet(timeout=1.0)
                    _packet_count += 1
                    if _packet_count <= 10 or packet_id == pkts.get("cb_keep_alive") or packet_id == pkts.get("cb_disconnect"):
                        _dprint(f"[Play调试] 收到包: id=0x{packet_id:02x}, len={len(data)}")
                except socket.timeout:
                    # 定期发送位置更新，防止服务器超时断开（每5秒一次）
                    # 只有收到过teleport包（知道真实位置）后才发送，避免位置全0导致服务器解码异常
                    if self._has_position:
                        now = time.time()
                        if now - self._last_pos_update >= 5.0:
                            self._last_pos_update = now
                            try:
                                # 优先用最简单的Player Movement包（只有onGround，1字节），最不容易出错
                                move_pkt = pkts.get("sb_player_movement")
                                if move_pkt is not None:
                                    self.conn.send_packet(move_pkt, b'\x01')  # onGround=True
                                elif pkts.get("sb_player_position_look") is not None:
                                    # 回退：Player Position And Look
                                    payload = struct.pack(">ddd", self._pos_x, self._pos_y, self._pos_z) + struct.pack(">ff", self._pos_yaw, self._pos_pitch) + b'\x01'
                                    self.conn.send_packet(pkts["sb_player_position_look"], payload)
                                elif pkts.get("sb_player_position") is not None:
                                    # 回退：Player Position
                                    payload = struct.pack(">ddd", self._pos_x, self._pos_y, self._pos_z) + b'\x01'
                                    self.conn.send_packet(pkts["sb_player_position"], payload)
                            except Exception:
                                pass
                    continue
                except Exception as _e:
                    _dprint(f"[Play调试] recv异常退出: {type(_e).__name__}: {_e}")
                    break

                # 先让版本协议处理器接管，返回True表示已处理，子类可选择性覆盖
                if self.protocol_handler.handle_play_packet(packet_id, data):
                    continue

                if packet_id == pkts["cb_keep_alive"]:
                    if len(data) >= 8:
                        try:
                            self.conn.send_packet(pkts["sb_keep_alive"], data[:8])
                            _dprint(f"[Play调试] 已回复keep_alive")
                        except Exception as _e:
                            _dprint(f"[Play调试] 回复keep_alive失败: {_e}")
                            break
                elif packet_id == pkts.get("cb_teleport"):
                    try:
                        # Player Position And Look: x(8)+y(8)+z(8)+yaw(4)+pitch(4)+flags(1) [+teleportId(varint), 1.17+]
                        stream = BytesStream(data)
                        x = struct.unpack(">d", stream.read(8))[0]
                        y = struct.unpack(">d", stream.read(8))[0]
                        z = struct.unpack(">d", stream.read(8))[0]
                        yaw = struct.unpack(">f", stream.read(4))[0]
                        pitch = struct.unpack(">f", stream.read(4))[0]
                        stream.read(1)  # flags: 位掩码（相对坐标）
                        # 保存当前位置（用于定期位置更新）
                        self._pos_x, self._pos_y, self._pos_z = x, y, z
                        self._pos_yaw, self._pos_pitch = yaw, pitch
                        self._has_position = True
                        # 1.17+ 有 teleport_id，旧版本没有
                        teleport_id = None
                        try:
                            teleport_id = read_varint_from_stream(stream)
                        except Exception:
                            pass
                        if pkts.get("sb_confirm_teleport") is not None and teleport_id is not None:
                            self.conn.send_packet(pkts["sb_confirm_teleport"], write_varint(teleport_id))
                        elif pkts.get("sb_player_position_look") is not None:
                            # 旧版本（1.12.2等）：回复 Player Position And Look 确认传送
                            payload = struct.pack(">ddd", x, y, z) + struct.pack(">ff", yaw, pitch) + b'\x01'
                            self.conn.send_packet(pkts["sb_player_position_look"], payload)
                    except Exception:
                        pass
                elif packet_id == pkts.get("cb_ping"):
                    if len(data) >= 4:
                        try:
                            self.conn.send_packet(pkts["sb_pong"], data[:4])
                        except Exception:
                            break
                elif packet_id == pkts.get("cb_disconnect"):
                    try:
                        from .buffer import read_string_from_stream
                        reason, _ = read_string_from_stream(data, 0)
                        _dprint(f"[Play调试] 服务器断开连接: {reason[:200]}")
                    except Exception:
                        _dprint(f"[Play调试] 服务器断开连接(无法解析原因), len={len(data)}")
                    break
                elif packet_id == pkts.get("cb_player_info"):
                    self.protocol_handler.parse_player_info(data)
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
                                pass
                    except Exception:
                        pass
                elif packet_id == pkts.get("cb_chat_message") or packet_id == pkts.get("cb_system_chat") or packet_id == pkts.get("cb_profileless_chat"):
                    # 聊天消息 — 提取文本用于插件抓取/命令响应
                    try:
                        is_profileless = (packet_id == pkts.get("cb_profileless_chat"))
                        is_system = (packet_id == pkts.get("cb_system_chat"))
                        if is_profileless:
                            # 无签名玩家聊天（离线服常见）：格式=JSON组件，sender从JSON的with[0]提取
                            text, sender = self._extract_profileless_chat(data)
                        else:
                            text, sender = self._extract_chat_with_sender(data, is_system)
                        if text:
                            with self._chat_lock:
                                self.chat_messages.append(text)
                                # 截断而非 deque：保持 routes_tools/plugins/command_runner 的
                                # [before:] 切片用法兼容，同时防止长时运行内存无界增长
                                if len(self.chat_messages) > self.MAX_CHAT_MESSAGES:
                                    del self.chat_messages[: len(self.chat_messages) - self.MAX_CHAT_MESSAGES]
                            if self.chat_callback:
                                try:
                                    self.chat_callback(text, sender)
                                except Exception:
                                    pass
                    except Exception as e:
                        print(f"[DEBUG chat] 解析异常: {e}")
        finally:
            # 循环退出（掉线/被断开/停止）即视为连接结束，观察者据此判断
            _dprint(f"[Play调试] Play线程退出, 共收到{_packet_count}个包")
            self.connected = False

    def _extract_chat_with_sender(self, data: bytes, is_system: bool):
        """从聊天包提取 (text, sender)，sender 为玩家名或'系统'"""
        sender = "系统"
        try:
            if not is_system:
                sender = self.protocol_handler.extract_chat_sender(data)
        except Exception:
            pass
        text = self._extract_chat_text(data, is_system)
        # 旧版本（1.12.2等）聊天格式为 "<玩家名> 消息"，sender 嵌在 text 里
        if not is_system and sender == "未知玩家" and text.startswith("<"):
            gt = text.find(">")
            if gt > 1 and gt < 20:
                sender = text[1:gt]
                text = text[gt + 1:].lstrip()
        return text, sender

    def _extract_profileless_chat(self, data: bytes):
        """无签名玩家聊天（profileless_chat）：格式=JSON组件，sender从with[0]提取"""
        from .buffer import BytesStream, read_string_from_stream
        try:
            stream = BytesStream(data)
            json_str = read_string_from_stream(stream)
            text = self.protocol_handler._parse_json_chat(json_str)
            # 从JSON提取sender
            sender = "未知玩家"
            try:
                import json as _json
                obj = _json.loads(json_str)
                if isinstance(obj, dict):
                    with_args = obj.get("with", [])
                    if with_args and isinstance(with_args[0], dict):
                        sender = with_args[0].get("text") or with_args[0].get("insertion") or "未知玩家"
                    elif with_args and isinstance(with_args[0], str):
                        sender = with_args[0]
            except Exception:
                pass
            return text, sender
        except Exception:
            return "", "未知玩家"

    def _extract_chat_text(self, data: bytes, is_system: bool) -> str:
        """从聊天包 payload 中提取纯文本（委托给版本协议处理器）"""
        try:
            return self.protocol_handler.extract_chat_text(data, is_system)
        except Exception:
            return ""

    @staticmethod
    def _json_component_to_text(obj) -> str:
        """将 Minecraft JSON 聊天组件转为纯文本（委托 core/chat.py）"""
        return _chat.json_component_to_text(obj)

    # ---- 1.20.5+ system chat 使用 network NBT 编码的聊天组件 ----
    @staticmethod
    def _nbt_read_string(stream) -> str:
        """network NBT 字符串（委托 core/nbt.py）"""
        return _nbt.nbt_read_string(stream)

    @staticmethod
    def _nbt_skip_value(stream, tag: int):
        """跳过未知 NBT 值（委托 core/nbt.py）"""
        _nbt.nbt_skip_value(stream, tag)

    @staticmethod
    def _nbt_compound_to_text(stream) -> str:
        """解析 network NBT 聊天组件（委托 core/nbt.py）"""
        return _nbt.nbt_compound_to_text(stream)

    @staticmethod
    def _nbt_component_to_text(stream) -> str:
        """解析 network NBT 聊天组件根节点（委托 core/nbt.py）"""
        return _nbt.nbt_component_to_text(stream)


def join_and_warn(host: str, port: int = 25565, username: str = "SecurityBot",
                  messages: list | None = None, timeout: float = 20.0,
                  message_delay: float = 0.6, protocol_version: int | None = None,
                  authme_password: str | None = None,
                  connect_delay: float = 1.5, use_premium: bool = True) -> BotResult:
    """
    完整流程：连接 → 登录 → 发警告 → 退出
    保留 V1 的全部功能。
    """
    if messages is None:
        messages = DEFAULT_WARNING_MESSAGES
    result = BotResult(ip=host, port=port)
    bot = MCBot(host, port, protocol_version=protocol_version, username=username, timeout=timeout,
                 use_premium=use_premium)

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

        # 等待服务器完成Play阶段初始化（区块加载、玩家列表等）
        # 1.18.x等版本连接后立即发消息会导致服务器解码异常（Index out of bounds）
        if connect_delay > 0:
            time.sleep(connect_delay)

        # 发送警告消息
        for msg in messages:
            if not bot.connected:
                result.error = "发消息前连接已断开"
                break
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
