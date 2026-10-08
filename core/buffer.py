# -*- coding: utf-8 -*-
"""
VarInt / VarLong / String / UUID / Boolean 编解码工具。
零依赖纯标准库，支持 MC 协议所有基础数据类型。
"""
import struct
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
    """读取 VarInt，返回 (值, 新偏移)。
    按 MC 规范做 int32 符号扩展（write_varint(-1) 写出的 5 字节读回来应是 -1，
    而不是 4294967295）——read_varlong 一直是这么做的，这里原先漏了。"""
    result = 0
    num_read = 0
    while True:
        if offset + num_read >= len(data):
            raise ValueError("VarInt 数据不完整")
        byte = data[offset + num_read]
        result |= (byte & 0x7F) << (7 * num_read)
        num_read += 1
        # MC VarInt 最长 5 字节；原先判断在 break 之后，第 6 字节会被先收下再判断
        if num_read > 5:
            raise ValueError("VarInt 过长")
        if not (byte & 0x80):
            break
    if result >= (1 << 31):  # 符号扩展到 int32
        result -= (1 << 32)
    return result, offset + num_read


def read_varint_from_stream(stream) -> int:
    """从流读取 VarInt。
    这里的调用方基本是长度前缀/包 ID（都应当是非负的），所以**不做**符号扩展，
    由调用方自行校验负值；只做 5 字节上限校验。"""
    result = 0
    num_read = 0
    while True:
        b = stream.read(1)
        if len(b) == 0:
            raise ConnectionError("连接已关闭")
        byte = b[0]
        result |= (byte & 0x7F) << (7 * num_read)
        num_read += 1
        if num_read > 5:
            raise ValueError("VarInt 过长")
        if not (byte & 0x80):
            break
    return result


def write_varlong(value: int) -> bytes:
    """写入 VarLong（64位变长整型）。"""
    result = bytearray()
    value &= 0xFFFFFFFFFFFFFFFF
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        result.append(byte)
        if not value:
            break
    return bytes(result)


def read_varlong(data: bytes, offset: int = 0) -> tuple:
    """读取 VarLong（64位变长整型）。"""
    result = 0
    num_read = 0
    while True:
        if offset + num_read >= len(data):
            raise ValueError("VarLong 数据不完整")
        byte = data[offset + num_read]
        result |= (byte & 0x7F) << (7 * num_read)
        num_read += 1
        # 与 VarInt 同理：上限判断必须在 break 之前，否则会多接受 1 字节
        if num_read > 10:
            raise ValueError("VarLong 过长")
        if not (byte & 0x80):
            break
    if result >= (1 << 63):
        result -= (1 << 64)
    return result, offset + num_read


def write_string(s: str) -> bytes:
    encoded = s.encode("utf-8")
    return write_varint(len(encoded)) + encoded


def read_string(data: bytes, offset: int = 0) -> tuple:
    length, offset = read_varint(data, offset)
    # read_varint 现在会符号扩展，长度可能是负数：必须显式拒绝，
    # 否则负长度会通过下面的边界检查并产生错误的切片。
    if length < 0:
        raise ValueError(f"字符串长度非法: {length}")
    if offset + length > len(data):
        raise ValueError("字符串数据不完整")
    s = data[offset:offset + length].decode("utf-8", errors="replace")
    return s, offset + length


def read_string_from_stream(stream) -> str:
    length = read_varint_from_stream(stream)
    if length < 0:
        raise ValueError(f"字符串长度非法: {length}")
    if length > 1024 * 1024:  # 最大1MB，防止恶意服务器内存放大
        raise ValueError(f"字符串过大: {length}")
    data = stream.read(length)
    if len(data) != length:
        raise ConnectionError("字符串被截断")
    return data.decode("utf-8", errors="replace")


def write_uuid(u) -> bytes:
    """写入 UUID，支持 uuid.UUID 对象或字符串自动转换。"""
    if isinstance(u, str):
        u = uuid.UUID(u)
    return u.int.to_bytes(16, "big")


def read_uuid(data: bytes, offset: int = 0) -> tuple:
    """从 bytes 读取 UUID，返回 (uuid.UUID, new_offset)。"""
    if offset + 16 > len(data):
        raise ValueError("UUID 数据不完整")
    u = uuid.UUID(int=int.from_bytes(data[offset:offset + 16], "big"))
    return u, offset + 16


def read_uuid_from_stream(stream) -> uuid.UUID:
    data = stream.read(16)
    if len(data) != 16:
        raise ConnectionError("UUID 被截断")
    return uuid.UUID(int=int.from_bytes(data, "big"))


def write_boolean(value: bool) -> bytes:
    return b"\x01" if value else b"\x00"


def read_boolean(data: bytes, offset: int = 0) -> tuple:
    if offset >= len(data):
        raise ValueError("Boolean 数据不完整")
    return data[offset] != 0, offset + 1


def read_boolean_from_stream(stream) -> bool:
    b = stream.read(1)
    if len(b) == 0:
        raise ConnectionError("连接已关闭")
    return b[0] != 0


def write_ushort(value: int) -> bytes:
    """写入无符号短整型（2字节大端）。"""
    return (value & 0xFFFF).to_bytes(2, "big")


def read_ushort(data: bytes, offset: int = 0) -> tuple:
    if offset + 2 > len(data):
        raise ValueError("UShort 数据不完整")
    return int.from_bytes(data[offset:offset + 2], "big"), offset + 2


def write_long(value: int) -> bytes:
    """写入有符号长整型（8字节大端）。"""
    return value.to_bytes(8, "big", signed=True)


def read_long(data: bytes, offset: int = 0) -> tuple:
    if offset + 8 > len(data):
        raise ValueError("Long 数据不完整")
    return int.from_bytes(data[offset:offset + 8], "big", signed=True), offset + 8


def write_int(value: int) -> bytes:
    """写入有符号整型（4字节大端）。"""
    return value.to_bytes(4, "big", signed=True)


def read_int(data: bytes, offset: int = 0) -> tuple:
    if offset + 4 > len(data):
        raise ValueError("Int 数据不完整")
    return int.from_bytes(data[offset:offset + 4], "big", signed=True), offset + 4


def write_float(value: float) -> bytes:
    return struct.pack(">f", value)


def read_float(data: bytes, offset: int = 0) -> tuple:
    if offset + 4 > len(data):
        raise ValueError("Float 数据不完整")
    return struct.unpack(">f", data[offset:offset + 4])[0], offset + 4


def write_double(value: float) -> bytes:
    return struct.pack(">d", value)


def read_double(data: bytes, offset: int = 0) -> tuple:
    if offset + 8 > len(data):
        raise ValueError("Double 数据不完整")
    return struct.unpack(">d", data[offset:offset + 8])[0], offset + 8


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
