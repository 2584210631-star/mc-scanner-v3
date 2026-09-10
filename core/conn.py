# -*- coding: utf-8 -*-
"""
MC TCP 连接：收发包、长度前缀、可选压缩、状态管理。
融合 V1 的健壮性（半包处理、超时恢复）和 V2 的简洁设计。
"""
import io
import socket
import struct
import threading
import time
import zlib
from .buffer import write_varint, read_varint_from_stream, write_string

PROTO_STATE_HANDSHAKE = 0
PROTO_STATE_STATUS = 1
PROTO_STATE_LOGIN = 2
PROTO_STATE_CONFIGURATION = 3
PROTO_STATE_PLAY = 4

MAX_PACKET_SIZE = 2 * 1024 * 1024  # 单个包最大2MB，防止恶意服务器内存放大

# 全局代理（设置后所有MCConnection默认走代理）
_global_proxy = None
_global_proxy_lock = threading.Lock()
_global_proxy_manager = None  # ProxyManager实例，设置后每次连接自动轮换

def set_global_proxy(proxy):
    """设置全局代理（Proxy对象或None）。设置后所有新连接默认走代理。"""
    global _global_proxy
    with _global_proxy_lock:
        _global_proxy = proxy

def get_global_proxy():
    """获取当前全局代理。如果设置了ProxyManager，会自动轮换。"""
    global _global_proxy
    with _global_proxy_lock:
        if _global_proxy_manager is not None:
            p = _global_proxy_manager.get_proxy()
            if p is not None:
                return p
        return _global_proxy

def set_global_proxy_manager(manager):
    """设置全局ProxyManager，每次连接自动从它获取代理（轮换）。"""
    global _global_proxy_manager
    with _global_proxy_lock:
        _global_proxy_manager = manager


def _connect_via_socks5(sock, proxy_host, proxy_port, target_host, target_port, username="", password=""):
    """通过SOCKS5代理建立TCP连接。"""
    sock.connect((proxy_host, proxy_port))
    # 握手: VER=5, NMETHODS, METHODS
    if username and password:
        sock.sendall(b"\x05\x01\x02")  # 用户名密码认证
    else:
        sock.sendall(b"\x05\x01\x00")  # 无认证
    resp = sock.recv(2)
    if resp[0] != 0x05:
        raise ConnectionError("SOCKS5代理响应错误")
    if resp[1] == 0x02:
        # 用户名密码认证
        sock.sendall(b"\x01" + bytes([len(username)]) + username.encode() + bytes([len(password)]) + password.encode())
        auth_resp = sock.recv(2)
        if auth_resp[1] != 0x00:
            raise ConnectionError("SOCKS5代理认证失败")
    elif resp[1] != 0x00:
        raise ConnectionError("SOCKS5代理不支持的认证方式")
    # CONNECT请求: VER=5, CMD=1, RSV=0, ATYP=1(IPv4), DST.ADDR, DST.PORT
    try:
        addr_bytes = socket.inet_aton(target_host)
        sock.sendall(b"\x05\x01\x00\x01" + addr_bytes + struct.pack(">H", target_port))
    except OSError:
        # 域名，用ATYP=3
        host_bytes = target_host.encode()
        sock.sendall(b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + struct.pack(">H", target_port))
    resp = sock.recv(10)
    if resp[1] != 0x00:
        raise ConnectionError(f"SOCKS5代理连接失败，错误码={resp[1]}")


def _connect_via_http(sock, proxy_host, proxy_port, target_host, target_port, username="", password=""):
    """通过HTTP CONNECT代理建立TCP连接。"""
    sock.connect((proxy_host, proxy_port))
    auth_header = ""
    if username and password:
        import base64
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        auth_header = f"Proxy-Authorization: Basic {token}\r\n"
    request = f"CONNECT {target_host}:{target_port} HTTP/1.1\r\nHost: {target_host}:{target_port}\r\n{auth_header}\r\n"
    sock.sendall(request.encode())
    # 读取响应头
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            break
        resp += chunk
    if b"200" not in resp.split(b"\r\n")[0]:
        raise ConnectionError(f"HTTP代理连接失败: {resp.split(b'\\r\\n')[0].decode(errors='ignore')}")


class MCConnection:
    def __init__(self, host: str, port: int = 25565, timeout: float = 15.0, proxy=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.compression_threshold = -1
        self.state = PROTO_STATE_HANDSHAKE
        self._send_lock = threading.Lock()
        self.proxy = proxy  # Proxy对象或None

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        try:
            proxy = self.proxy if self.proxy is not None else get_global_proxy()
            # 本地/私有地址不走代理（否则会连到代理服务器的本地）
            if proxy is not None:
                import ipaddress
                try:
                    addr = ipaddress.ip_address(self.host)
                    if addr.is_private or addr.is_loopback or addr.is_link_local:
                        proxy = None
                except ValueError:
                    pass
            if proxy is not None:
                if proxy.proto == "socks5":
                    _connect_via_socks5(self.sock, proxy.host, proxy.port,
                                        self.host, self.port,
                                        proxy.username, proxy.password)
                else:
                    _connect_via_http(self.sock, proxy.host, proxy.port,
                                      self.host, self.port,
                                      proxy.username, proxy.password)
            else:
                self.sock.connect((self.host, self.port))
        except Exception:
            self.sock.close()
            self.sock = None
            raise

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
        with self._send_lock:
            import selectors
            sel = selectors.DefaultSelector()
            sel.register(self.sock, selectors.EVENT_WRITE)
            try:
                # 等待写就绪，不修改 socket.timeout，避免与 recv 线程竞态
                events = sel.select(timeout=self.timeout)
                if not events:
                    raise socket.timeout("send 等待写就绪超时")
                self.sock.sendall(frame)
            finally:
                sel.unregister(self.sock)
                sel.close()

    def recv_packet(self, timeout: float | None = None) -> tuple:
        """接收一个数据包，返回 (packet_id, payload_bytes)
        读包数据中途失败（半包）时关闭连接，避免后续流错位；
        仅等待数据时的正常超时不关闭连接（调用方用于轮询）。
        用 select 实现超时，不修改 socket.timeout，避免影响并发 send。"""
        if self.sock is None:
            raise ConnectionError("未连接")
        import selectors
        sel = selectors.DefaultSelector()
        sel.register(self.sock, selectors.EVENT_READ)
        try:
            if timeout is not None:
                events = sel.select(timeout=timeout)
                if not events:
                    raise socket.timeout("recv 超时")
            packet_length = self._recv_varint()
            if packet_length > MAX_PACKET_SIZE:
                self.close()
                raise ValueError(f"包过大: {packet_length} > {MAX_PACKET_SIZE}")
            if packet_length < 0:
                self.close()
                raise ValueError(f"包长度非法: {packet_length}")
            try:
                raw = self._recv_exact(packet_length, total_timeout=timeout or self.timeout)
            except socket.timeout:
                self.close()  # 读包中途超时=半包，关闭连接避免流错位
                raise
            except Exception:
                self.close()
                raise
        finally:
            sel.unregister(self.sock)
            sel.close()

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
        return result

    def _recv_exact(self, n: int, total_timeout: float = 15.0) -> bytes:
        buf = bytearray()
        deadline = time.time() + total_timeout
        while len(buf) < n:
            if time.time() > deadline:
                raise socket.timeout(f"读包中途超时（已读{len(buf)}/{n}）")
            try:
                chunk = self.sock.recv(n - len(buf))
            except socket.timeout:
                continue  # 短暂超时继续，但受 total_timeout 总限制
            if not chunk:
                raise ConnectionError("连接在读取中关闭")
            buf.extend(chunk)
        return bytes(buf)
