"""1.18.2及以下（协议 < 759）协议处理器"""
from __future__ import annotations
import struct, time
from .base import ProtocolHandler
from ..buffer import write_string, write_varint, BytesStream, read_string_from_stream, read_varint_from_stream, read_uuid_from_stream


class Handler(ProtocolHandler):
    protocol_version = 758
    version_name = "1.18.2及以下"

    def login_start_payload(self, username: str, uuid=None) -> bytes:
        return write_string(username)

    def send_chat_payload(self, message: str) -> bytes:
        return write_string(message[:256])

    def send_command_payload(self, command: str) -> bytes:
        # 旧版本用聊天消息发命令
        return write_string("/" + command[:255])

    def extract_chat_text(self, data: bytes, is_system: bool) -> str:
        import json
        try:
            stream = BytesStream(data)
            if is_system:
                json_str = read_string_from_stream(stream)
            else:
                json_str = read_string_from_stream(stream)  # message
                # 1.16（协议735）起聊天包增加 position 和 sender UUID
                # 1.12.2~1.15.2（协议340~578）只有 message 字段
                if getattr(self.bot, 'protocol_version', 758) >= 735:
                    stream.read(1)  # position
                    stream.read(16)  # sender UUID
            try:
                obj = json.loads(json_str)
                return self.bot._json_component_to_text(obj)
            except (json.JSONDecodeError, TypeError):
                return json_str
        except Exception:
            return ""

    def extract_chat_sender(self, data: bytes) -> str:
        try:
            stream = BytesStream(data)
            json_str = read_string_from_stream(stream)  # message
            if getattr(self.bot, 'protocol_version', 758) >= 735:
                stream.read(1)  # position
                uuid_bytes = stream.read(16)
                import uuid as _uuid
                uuid_str = str(_uuid.UUID(bytes=uuid_bytes))
                name = self.bot.player_list.get(uuid_str)
                if name:
                    return name
            # 1.12.2 无 sender UUID 字段，从 JSON 里的 chat.type.text 的 with[0] 提取
            try:
                import json
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
            return "未知玩家"
        except Exception:
            return "未知玩家"
