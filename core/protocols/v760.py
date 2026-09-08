"""1.19.1/1.19.2（协议 760）协议处理器，继承 761 仅覆盖差异"""
from __future__ import annotations
import struct, time
from .v761 import Handler as V761Handler
from ..buffer import write_string, write_varint, write_uuid, BytesStream, read_string_from_stream, read_boolean_from_stream


class Handler(V761Handler):
    protocol_version = 760
    version_name = "1.19.1/1.19.2"

    def login_start_payload(self, username: str, uuid=None) -> bytes:
        payload = write_string(username)
        payload += b'\x00' + b'\x01' + write_uuid(uuid)
        return payload

    def send_chat_payload(self, message: str) -> bytes:
        timestamp = int(time.time() * 1000)
        return (write_string(message[:256])
                + struct.pack(">q", timestamp)
                + struct.pack(">q", 0)
                + b'\x00'
                + b'\x00'
                + b'\x00'
                + write_varint(0))

    def send_command_payload(self, command: str) -> bytes:
        timestamp = int(time.time() * 1000)
        return (write_string(command[:256])
                + struct.pack(">q", timestamp)
                + struct.pack(">q", 0)
                + b'\x00' + b'\x00' + b'\x00' + write_varint(0))

    def extract_chat_text(self, data: bytes, is_system: bool) -> str:
        try:
            stream = BytesStream(data)
            if is_system:
                json_str = read_string_from_stream(stream)
            else:
                stream.read(16)  # senderUuid
                stream.read(1)   # index (Byte, 760特有)
                if read_boolean_from_stream(stream):
                    slen = read_varint_from_stream(stream)
                    stream.read(slen)
                json_str = read_string_from_stream(stream)
            return self._parse_json_chat(json_str)
        except Exception:
            return ""
