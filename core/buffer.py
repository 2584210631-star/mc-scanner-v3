# -*- coding: utf-8 -*-
"""
VarInt / VarLong / String / UUID 编解码工具。
从 mc_protocol.py 拆分，零依赖纯标准库。
"""
import io
import uuid


def write_varint(value: int) -> bytes:
    result = bytearray()
    value &= 0xFFFFFFFF
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        result.append(byte)
        if not value:
            break
    return bytes(result)


def read_varint(data: bytes, offset: int = 0) -> tuple:
    result = 0
    num_read = 0
    while True:
        if offset + num_read >= len(data):
            raise ValueError("VarInt 数据不完整")
        byte = data[offset + num_read]
        result |= (byte & 0x7F) << (7 * num_read)
        num_read += 1
        if not (byte & 0x80):
            break
        if num_read > 5:
            raise ValueError("VarInt 过长")
    if result >= (1 << 31):
        result -= (1 << 32)
    return result, offset + num_read


def read_varint_from_stream(stream) -> int:
    result = 0
    num_read = 0
    while True:
        b = stream.read(1)
        if len(b) == 0:
            raise ConnectionError("连接已关闭")
        byte = b[0]
        result |= (byte & 0x7F) << (7 * num_read)
        num_read += 1
        if not (byte & 0x80):
            break
        if num_read > 5:
            raise ValueError("VarInt 过长")
    if result >= (1 << 31):
        result -= (1 << 32)
    return result


def write_string(s: str) -> bytes:
    encoded = s.encode("utf-8")
    return write_varint(len(encoded)) + encoded


def read_string(data: bytes, offset: int = 0) -> tuple:
    length, offset = read_varint(data, offset)
    if offset + length > len(data):
        raise ValueError("字符串数据不完整")
    s = data[offset:offset + length].decode("utf-8", errors="replace")
    return s, offset + length


def read_string_from_stream(stream) -> str:
    length = read_varint_from_stream(stream)
    data = stream.read(length)
    if len(data) != length:
        raise ConnectionError("字符串被截断")
    return data.decode("utf-8", errors="replace")


def write_uuid(u: uuid.UUID) -> bytes:
    return u.int.to_bytes(16, "big")


def read_uuid_from_stream(stream) -> uuid.UUID:
    data = stream.read(16)
    if len(data) != 16:
        raise ConnectionError("UUID 被截断")
    return uuid.UUID(int=int.from_bytes(data, "big"))


def offline_uuid(username: str) -> uuid.UUID:
    """离线模式玩家 UUID 的标准生成方式"""
    return uuid.uuid3(uuid.NAMESPACE_OID, f"OfflinePlayer:{username}")


class BytesStream:
    """把 bytes 包装成带 read 的流对象，复用流读取函数"""
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = len(self.data) - self.pos
        chunk = self.data[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk
