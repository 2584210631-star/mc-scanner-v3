"""1.19（协议 759）协议处理器"""
from __future__ import annotations
import struct, time
from .base import ProtocolHandler
from ..buffer import write_string, write_varint, write_uuid, BytesStream, read_string_from_stream, read_varint_from_stream, read_boolean_from_stream, read_uuid_from_stream


class Handler(ProtocolHandler):
    protocol_version = 759
    version_name = "1.19"

    def login_start_payload(self, username: str, uuid=None) -> bytes:
        payload = write_string(username)
        if uuid:
            payload += b'\x01' + write_uuid(uuid)  # hasPlayerUUID=true + UUID
        return payload

    def send_chat_payload(self, message: str) -> bytes:
        timestamp = int(time.time() * 1000)
        return (write_string(message[:256])
                + struct.pack(">q", timestamp)
                + struct.pack(">q", 0)
                + b'\x00'  # hasSignature=false
                + b'\x00')  # signedPreview=false

    def send_command_payload(self, command: str) -> bytes:
        # 1.19 命令包格式同聊天包
        timestamp = int(time.time() * 1000)
        return (write_string(command[:256])
                + struct.pack(">q", timestamp)
                + struct.pack(">q", 0)
                + b'\x00' + b'\x00')

    def extract_chat_text(self, data: bytes, is_system: bool) -> str:
        import json
        try:
            stream = BytesStream(data)
            if is_system:
                json_str = read_string_from_stream(stream)
            else:
                stream.read(16)  # UUID
                read_string_from_stream(stream)  # nickname
                stream.read(8)  # timestamp
                stream.read(8)  # salt
                has_sig = read_boolean_from_stream(stream)
                if has_sig:
                    stream.read(256)  # signature
                json_str = read_string_from_stream(stream)
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
            stream.read(16)  # UUID
            nick_json = read_string_from_stream(stream)
            import json
            try:
                return self.bot._json_component_to_text(json.loads(nick_json))
            except Exception:
                return nick_json
        except Exception:
            return "未知玩家"
