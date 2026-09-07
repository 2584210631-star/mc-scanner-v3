"""1.19.3-1.20.4（协议 761-765）协议处理器
761-763: Login Start 有 hasPlayerUUID 字段
764-765: Login Start 直接 UUID，有 Configuration 阶段"""
from __future__ import annotations
import struct, time
from .base import ProtocolHandler
from ..buffer import write_string, write_varint, write_uuid, BytesStream, read_string_from_stream, read_varint_from_stream, read_boolean_from_stream, read_uuid_from_stream


class Handler(ProtocolHandler):
    protocol_version = 761
    version_name = "1.19.3-1.20.4"

    def login_start_payload(self, username: str, uuid=None) -> bytes:
        payload = write_string(username)
        if self.bot.protocol_version >= 764:
            # 1.20.2+ (764+): 直接 UUID
            payload += write_uuid(uuid)
        else:
            # 1.19.3-1.20.1 (761-763): hasPlayerUUID(true) + UUID
            payload += b'\x01' + write_uuid(uuid)
        return payload

    def send_chat_payload(self, message: str) -> bytes:
        timestamp = int(time.time() * 1000)
        return (write_string(message[:256])
                + struct.pack(">q", timestamp)
                + struct.pack(">q", 0)
                + b'\x00'  # hasSignature=false
                + write_varint(0)  # signedPreview=false (VarInt)
                + b"\x00\x00\x00")  # acknowledgment 3字节

    def send_command_payload(self, command: str) -> bytes:
        # 1.19.3-1.20.4 用聊天消息发命令（最兼容，命令包格式复杂易出错）
        return self.send_chat_payload("/" + command[:255])

    def extract_chat_text(self, data: bytes, is_system: bool) -> str:
        import json
        try:
            stream = BytesStream(data)
            if is_system:
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
