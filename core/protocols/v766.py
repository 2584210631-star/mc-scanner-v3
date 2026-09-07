"""1.20.5-1.21.10（协议 766-773）协议处理器"""
from __future__ import annotations
import struct, time
from .base import ProtocolHandler
from ..buffer import write_string, write_varint, write_uuid, BytesStream, read_string_from_stream, read_varint_from_stream, read_boolean_from_stream


class Handler(ProtocolHandler):
    protocol_version = 766
    version_name = "1.20.5-1.21.10"

    def login_start_payload(self, username: str, uuid=None) -> bytes:
        return write_string(username) + write_uuid(uuid)

    def send_chat_payload(self, message: str) -> bytes:
        timestamp = int(time.time() * 1000)
        return (write_string(message[:256])
                + struct.pack(">q", timestamp)
                + struct.pack(">q", 0)
                + b'\x00' * 5)  # 尾部5字节

    def send_command_payload(self, command: str) -> bytes:
        # 1.20.5+ Chat Command包：只有command字段
        return write_string(command[:256])

    def extract_chat_text(self, data: bytes, is_system: bool) -> str:
        import json
        try:
            stream = BytesStream(data)
            if is_system:
                # 1.20.5+ System Chat 是 Network NBT
                try:
                    txt = self.bot._nbt_component_to_text(stream)
                    if txt:
                        return txt
                except Exception:
                    pass
                json_str = read_string_from_stream(stream)
            else:
                stream.read(16)  # senderUuid
                read_varint_from_stream(stream)  # index
                if read_boolean_from_stream(stream):  # hasSignature
                    sig_len = read_varint_from_stream(stream)
                    stream.read(sig_len)  # signature
                json_str = read_string_from_stream(stream)  # message
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
            uuid_bytes = stream.read(16)
            import uuid as _uuid
            uuid_str = str(_uuid.UUID(bytes=uuid_bytes))
            return self.bot.player_list.get(uuid_str, "未知玩家")
        except Exception:
            return "未知玩家"
