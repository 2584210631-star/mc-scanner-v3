"""Minecraft 26.1（协议 775）协议处理器，继承 774
26.1 变化：
- PLAYER_CHAT 包开头新增 Global Index (VarInt)，然后才是 Sender UUID
- 聊天包 hasSignature+messageCount → signature(option)+offset
- 无签名时编码结果与 774 相同"""
from __future__ import annotations
from .v774 import Handler as V774Handler
from ..buffer import BytesStream, read_varint_from_stream, read_string_from_stream, read_boolean_from_stream


class Handler(V774Handler):
    protocol_version = 775
    version_name = "26.1"

    def extract_chat_text(self, data: bytes, is_system: bool) -> str:
        """26.1 PLAYER_CHAT: Global Index(VarInt) + Sender UUID + Index + Signature + Message + ..."""
        try:
            stream = BytesStream(data)
            if is_system:
                saved_pos = stream.pos
                try:
                    txt = self.bot._nbt_component_to_text(stream)
                    if txt:
                        return txt
                except Exception:
                    pass
                stream.pos = saved_pos
                return read_string_from_stream(stream)
            # 玩家聊天：跳过 Global Index
            read_varint_from_stream(stream)
            stream.read(16)  # Sender UUID
            read_varint_from_stream(stream)  # Index
            # signature: option<buffer(256)>
            if read_boolean_from_stream(stream):
                stream.read(256)
            json_str = read_string_from_stream(stream)
            return self._parse_json_chat(json_str)
        except Exception:
            return ""

    def extract_chat_sender(self, data: bytes) -> str:
        """26.1 PLAYER_CHAT: 先跳过 Global Index，再读 Sender UUID"""
        try:
            stream = BytesStream(data)
            read_varint_from_stream(stream)  # Global Index
            uuid_bytes = stream.read(16)
            name = self._sender_from_uuid(uuid_bytes)
            if name:
                return name
            return "未知玩家"
        except Exception:
            return "未知玩家"
