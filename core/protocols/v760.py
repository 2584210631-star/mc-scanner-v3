"""1.19.1/1.19.2（协议 760）协议处理器"""
from __future__ import annotations
import struct, time
from .base import ProtocolHandler
from ..buffer import write_string, write_varint, write_uuid, BytesStream, read_string_from_stream, read_varint_from_stream, read_boolean_from_stream, read_uuid_from_stream


class Handler(ProtocolHandler):
    protocol_version = 760
    version_name = "1.19.1/1.19.2"

    def login_start_payload(self, username: str, uuid=None) -> bytes:
        payload = write_string(username)
        # hasProfileKey(false) + hasPlayerUUID(true) + UUID
        payload += b'\x00' + b'\x01' + write_uuid(uuid)
        return payload

    def send_chat_payload(self, message: str) -> bytes:
        timestamp = int(time.time() * 1000)
        return (write_string(message[:256])
                + struct.pack(">q", timestamp)
                + struct.pack(">q", 0)
                + b'\x00'  # hasSignature=false
                + b'\x00'  # signedPreview=false
                + b'\x00'  # hasChatSession=false
                + write_varint(0))  # acknowledgment=0

    def send_command_payload(self, command: str) -> bytes:
        timestamp = int(time.time() * 1000)
        return (write_string(command[:256])
                + struct.pack(">q", timestamp)
                + struct.pack(">q", 0)
                + b'\x00' + b'\x00' + b'\x00' + write_varint(0))

    def extract_chat_text(self, data: bytes, is_system: bool) -> str:
        import json
        try:
            stream = BytesStream(data)
            if is_system:
                json_str = read_string_from_stream(stream)
            else:
                stream.read(16)  # senderUuid
                stream.read(1)   # index (Byte!)
                if read_boolean_from_stream(stream):  # hasSignature
                    slen = read_varint_from_stream(stream)
                    stream.read(slen)  # signature
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
