"""1.21.11+（协议 774+）协议处理器，继承 766 仅覆盖差异"""
from __future__ import annotations
import struct, time
from .v766 import Handler as V766Handler
from ..buffer import write_string, write_varint


class Handler(V766Handler):
    protocol_version = 774
    version_name = "1.21.11+"

    def send_chat_payload(self, message: str) -> bytes:
        timestamp = int(time.time() * 1000)
        return (write_string(message[:256])
                + struct.pack(">q", timestamp)
                + struct.pack(">q", 0)
                + b'\x00'           # hasSignature=false
                + write_varint(0)   # messageCount=0
                + b"\x00\x00\x00"   # acknowledged: 固定3字节BitSet
                + b'\x00')          # checksum: 0=IGNORE_CHECKSUM（1.21.5+新增）
