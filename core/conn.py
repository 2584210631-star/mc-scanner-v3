# -*- coding: utf-8 -*-
"""
MC TCP 连接：收发包、长度前缀、可选压缩、状态管理。
融合 V1 的健壮性（半包处理、超时恢复）和 V2 的简洁设计。
"""
import io
import socket
import zlib
from .buffer import write_varint, read_varint_from_stream, write_string

PROTO_STATE_HANDSHAKE = 0
PROTO_STATE_STATUS = 1
PROTO_STATE_LOGIN = 2
PROTO_STATE_CONFIGURATION = 3
PROTO_STATE_PLAY = 4


class MCConnection:
    def __init__(self, host: str, port: int = 25565, timeout: float = 15.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.compression_threshold = -1
        self.state = PROTO_STATE_HANDSHAKE

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))

    def close(self):
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def handshake(self, protocol: int, next_state: int):
        payload = (write_varint(protocol) + write_string(self.host)
                   + self.port.to_bytes(2, "big") + write_varint(next_state))
        self.send_packet(0x00, payload)
        self.state = next_state

    def set_compression(self, threshold: int):
        self.compression_threshold = threshold

    def send_packet(self, packet_id: int, payload: bytes = b""):
        if self.sock is None:
            raise ConnectionError("未连接")
        id_bytes = write_varint(packet_id)
        uncompressed = id_bytes + payload
        if self.compression_threshold >= 0:
            if len(uncompressed) >= self.compression_threshold:
                data_length = write_varint(len(uncompressed))
                compressed = zlib.compress(uncompressed)
                packet_data = data_length + compressed
            else:
                packet_data = write_varint(0) + uncompressed
        else:
            packet_data = uncompressed
        frame = write_varint(len(packet_data)) + packet_data
        self.sock.sendall(frame)

    def recv_packet(self, timeout: float | None = None) -> tuple:
        """接收一个数据包，返回 (packet_id, payload_bytes)
        读包数据中途失败（半包）时关闭连接，避免后续流错位；
        仅等待数据时的正常超时不关闭连接（调用方用于轮询）
        """
        if self.sock is None:
            raise ConnectionError("未连接")
        if timeout is not None:
            self.sock.settimeout(timeout)
        try:
            packet_length = self._recv_varint()
            try:
                raw = self._recv_exact(packet_length)
            except Exception:
                self.close()
                raise
        finally:
            if timeout is not None and self.sock is not None:
                try:
                    self.sock.settimeout(self.timeout)
                except Exception:
                    pass

        if self.compression_threshold >= 0:
            buf = io.BytesIO(raw)
            data_length = read_varint_from_stream(buf)
            remaining = buf.read()
            if data_length == 0:
                decompressed = remaining
            else:
                decompressed = zlib.decompress(remaining)
        else:
            decompressed = raw
        buf = io.BytesIO(decompressed)
        packet_id = read_varint_from_stream(buf)
        payload = buf.read()
        return packet_id, payload

    def _recv_varint(self) -> int:
        result = 0
        num_read = 0
        while True:
            b = self.sock.recv(1)
            if not b:
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

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("连接在读取中关闭")
            buf.extend(chunk)
        return bytes(buf)
