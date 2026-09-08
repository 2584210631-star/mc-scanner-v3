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
        payload = (write_string(message[:256])
                   + struct.pack(">q", timestamp)
                   + struct.pack(">q", 0)
                   + b'\x00'           # hasSignature=false
                   + write_varint(0)   # messageCount=0
                   + b"\x00\x00\x00")  # acknowledged: FixedBitSet固定3字节（1.20.5+无长度前缀）
        # 1.21.5+ (769+) 增加 checksum 字节，无签名消息=1
        if getattr(self.bot, 'protocol_version', 766) >= 769:
            payload += b'\x01'
        return payload

    def send_command_payload(self, command: str) -> bytes:
        return write_string(command[:256])

    def get_client_info_extra(self) -> bytes:
        """1.21.4+ (769+) Client Information 增加 particleStatus"""
        if getattr(self.bot, 'protocol_version', 766) >= 769:
            return write_varint(0)
        return b""

    def extract_chat_text(self, data: bytes, is_system: bool) -> str:
        try:
            stream = BytesStream(data)
            if is_system:
                try:
                    txt = self.bot._nbt_component_to_text(stream)
                    if txt:
                        return txt
                except Exception:
                    pass
                json_str = read_string_from_stream(stream)
            else:
                stream.read(16)
                read_varint_from_stream(stream)
                if read_boolean_from_stream(stream):
                    sig_len = read_varint_from_stream(stream)
                    stream.read(sig_len)
                json_str = read_string_from_stream(stream)
            return self._parse_json_chat(json_str)
        except Exception:
            return ""

    def extract_chat_sender(self, data: bytes) -> str:
        try:
            stream = BytesStream(data)
            uuid_bytes = stream.read(16)
            name = self._sender_from_uuid(uuid_bytes)
            if name:
                return name
            name = self._sender_from_json(stream)
            return name or "未知玩家"
        except Exception:
            return "未知玩家"
