"""1.18.2及以下（协议 < 759）协议处理器"""
from __future__ import annotations
from .base import ProtocolHandler
from ..buffer import write_string, BytesStream, read_string_from_stream


class Handler(ProtocolHandler):
    protocol_version = 758
    version_name = "1.18.2及以下"

    def login_start_payload(self, username: str, uuid=None) -> bytes:
        return write_string(username)

    def send_chat_payload(self, message: str) -> bytes:
        return write_string(message[:256])

    def send_command_payload(self, command: str) -> bytes:
        return write_string("/" + command[:255])

    def extract_chat_text(self, data: bytes, is_system: bool) -> str:
        try:
            stream = BytesStream(data)
            json_str = read_string_from_stream(stream)
            # 1.16（协议735）起聊天包增加 position 和 sender UUID
            if getattr(self.bot, 'protocol_version', 758) >= 735:
                stream.read(1)
                stream.read(16)
            return self._parse_json_chat(json_str)
        except Exception:
            return ""

    def extract_chat_sender(self, data: bytes) -> str:
        # 1.12.2 无 sender UUID，sender 嵌在 text 的 <> 前缀中，由 bot._extract_chat_with_sender 统一处理
        # 1.16+ 有 UUID，从 player_list 查
        try:
            stream = BytesStream(data)
            read_string_from_stream(stream)
            if getattr(self.bot, 'protocol_version', 758) >= 735:
                stream.read(1)
                uuid_bytes = stream.read(16)
                name = self._sender_from_uuid(uuid_bytes)
                if name:
                    return name
        except Exception:
            pass
        return "未知玩家"
