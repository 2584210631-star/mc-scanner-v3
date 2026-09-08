"""协议处理器基类 — 每个版本继承并实现自己的格式"""
from __future__ import annotations
from typing import Optional, Tuple
import json


class ProtocolHandler:
    """版本协议处理器基类。子类只负责自己版本的包格式。"""

    protocol_version: int = 0
    version_name: str = "unknown"

    def __init__(self, bot):
        self.bot = bot

    # ---- 登录阶段 ----
    def login_start_payload(self, username: str, uuid: Optional[str] = None) -> bytes:
        """构造 Login Start 包 payload"""
        raise NotImplementedError

    # ---- 配置阶段 ----
    def do_configuration(self) -> bool:
        """处理 Configuration 阶段，返回是否成功"""
        return True

    # ---- 聊天发送 ----
    def send_chat_payload(self, message: str) -> bytes:
        """构造聊天消息包 payload"""
        raise NotImplementedError

    def send_command_payload(self, command: str) -> bytes:
        """构造命令包 payload（不含前导 /）"""
        raise NotImplementedError

    # ---- 聊天接收 ----
    def extract_chat_text(self, data: bytes, is_system: bool) -> str:
        """从聊天包提取纯文本"""
        return ""

    def extract_chat_sender(self, data: bytes) -> str:
        """从聊天包提取发送者名字"""
        return "未知玩家"

    # ---- Play 阶段包处理 ----
    def handle_play_packet(self, packet_id: int, data: bytes) -> bool:
        """处理一个 play 阶段包。返回 True 表示已处理，False 表示未识别。"""
        return False

    def parse_player_info(self, data: bytes) -> None:
        """解析 Player Info Update 包，更新 bot.player_list 和 player_callback。
        各版本按自己的格式覆盖。"""
        pass

    def get_client_info_extra(self) -> bytes:
        """Configuration 阶段 Client Information 包的版本特有额外字段。"""
        return b""

    # ===== 通用辅助方法（各版本共用，减少重复）=====

    @staticmethod
    def _parse_json_chat(json_str: str) -> str:
        """解析 JSON 聊天组件为纯文本（带翻译表）"""
        try:
            obj = json.loads(json_str)
            from ..bot import MCBot
            return MCBot._json_component_to_text(obj)
        except (json.JSONDecodeError, TypeError):
            return json_str

    def _sender_from_uuid(self, uuid_bytes: bytes) -> str:
        """从 UUID 字节查 player_list 获取玩家名，查不到返回空串"""
        try:
            import uuid as _uuid
            uuid_str = str(_uuid.UUID(bytes=uuid_bytes))
            return self.bot.player_list.get(uuid_str, "")
        except Exception:
            return ""

    def _sender_from_json(self, stream) -> str:
        """从聊天 JSON 的 chat.type.text.with[0] 提取 sender（player_list查不到时的fallback）"""
        try:
            from ..buffer import read_varint_from_stream, read_boolean_from_stream, read_string_from_stream
            read_varint_from_stream(stream)  # index
            if read_boolean_from_stream(stream):  # hasSignature
                sig_len = read_varint_from_stream(stream)
                stream.read(sig_len)
            json_str = read_string_from_stream(stream)
            obj = json.loads(json_str)
            if isinstance(obj, dict) and obj.get("translate") == "chat.type.text":
                with_args = obj.get("with", [])
                if with_args:
                    sender_obj = with_args[0]
                    if isinstance(sender_obj, dict):
                        return sender_obj.get("text", "") or str(sender_obj)
                    return str(sender_obj)
        except Exception:
            pass
        return ""
