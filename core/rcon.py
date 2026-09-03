# -*- coding: utf-8 -*-
"""
RCON 客户端：纯 Python 实现 Minecraft RCON 协议。
支持连接、认证、执行命令、多包响应。

吸收自 MCPTool (zxcursed0/MCPTool) 的 RCON 功能。
"""
import socket
import struct
import time
from typing import Optional

# RCON 包类型
RCON_TYPE_LOGIN = 3
RCON_TYPE_COMMAND = 2
RCON_TYPE_RESPONSE = 0
RCON_TYPE_AUTH_RESPONSE = 2

# 特殊请求 ID（用于检测多包响应结束）
RCON_END_MARKER = 0x42424242


class RCONError(Exception):
    pass


class RCONClient:
    """Minecraft RCON 客户端"""

    def __init__(self, host: str, port: int = 25575, password: str = "",
                 timeout: float = 10.0):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.authenticated = False
        self._request_id = 1

    def connect(self) -> bool:
        """连接到 RCON 服务器并认证"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        try:
            self.sock.connect((self.host, self.port))
        except Exception as e:
            self.sock.close()
            self.sock = None
            raise RCONError(f"连接失败: {e}")

        # 发送认证包
        self._send_packet(RCON_TYPE_LOGIN, self.password)
        resp_id, resp_type, resp_body = self._recv_packet()
        if resp_type != RCON_TYPE_AUTH_RESPONSE or resp_id == -1:
            self.close()
            raise RCONError("RCON 认证失败（密码错误）")
        self.authenticated = True
        return True

    def execute(self, command: str, timeout: float | None = None) -> str:
        """执行 RCON 命令，返回响应文本"""
        if not self.authenticated:
            raise RCONError("未认证")
        if command.startswith("/"):
            command = command[1:]

        req_id = self._next_id()
        self._send_packet(RCON_TYPE_COMMAND, command, req_id)

        # 发送一个空命令来标记响应结束（用于多包响应）
        marker_id = self._next_id()
        self._send_packet(RCON_TYPE_COMMAND, "", marker_id)

        # 收集所有响应包，直到收到 marker 的响应
        response_parts = []
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            try:
                resp_id, resp_type, resp_body = self._recv_packet()
            except socket.timeout:
                break
            if resp_id == marker_id:
                break
            if resp_id == req_id and resp_type == RCON_TYPE_RESPONSE:
                response_parts.append(resp_body)
            # 其他包（如 marker 的响应可能先到）忽略

        return "".join(response_parts).strip()

    def execute_many(self, commands: list[str], delay: float = 0.3) -> dict[str, str]:
        """批量执行命令，返回 {命令: 响应} 字典"""
        results = {}
        for cmd in commands:
            try:
                results[cmd] = self.execute(cmd)
            except Exception as e:
                results[cmd] = f"ERROR: {e}"
            time.sleep(delay)
        return results

    def close(self):
        """关闭连接"""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.authenticated = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def _next_id(self) -> int:
        rid = self._request_id
        self._request_id += 1
        if self._request_id >= RCON_END_MARKER:
            self._request_id = 1
        return rid

    def _send_packet(self, packet_type: int, body: str, request_id: int | None = None):
        if self.sock is None:
            raise RCONError("未连接")
        if request_id is None:
            request_id = self._next_id()
        body_bytes = body.encode("utf-8")
        # 包结构：长度(4) + 请求ID(4) + 类型(4) + 正文 + 空字节(2)
        payload = struct.pack("<ii", request_id, packet_type) + body_bytes + b"\x00\x00"
        self.sock.sendall(struct.pack("<i", len(payload)) + payload)

    def _recv_packet(self) -> tuple[int, int, str]:
        """接收一个 RCON 包，返回 (request_id, type, body)"""
        if self.sock is None:
            raise RCONError("未连接")
        # 读取长度
        length_data = self._recv_exact(4)
        length = struct.unpack("<i", length_data)[0]
        if length < 10 or length > 4096:
            raise RCONError(f"无效的包长度: {length}")
        # 读取包内容
        data = self._recv_exact(length)
        request_id = struct.unpack("<i", data[0:4])[0]
        packet_type = struct.unpack("<i", data[4:8])[0]
        body = data[8:-2].decode("utf-8", errors="replace")
        return request_id, packet_type, body

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("RCON 连接已关闭")
            buf.extend(chunk)
        return bytes(buf)


def rcon_execute(host: str, port: int, password: str, command: str,
                 timeout: float = 10.0) -> str:
    """便捷函数：连接 RCON 并执行单条命令"""
    with RCONClient(host, port, password, timeout) as client:
        return client.execute(command)


def rcon_bruteforce(host: str, port: int, passwords: list[str],
                     timeout: float = 5.0, delay: float = 0.5) -> tuple[bool, str]:
    """RCON 密码暴力破解（仅用于授权测试）。
    返回 (是否成功, 找到的密码或空字符串)
    """
    for pwd in passwords:
        try:
            client = RCONClient(host, port, pwd, timeout)
            client.connect()
            client.close()
            return True, pwd
        except RCONError:
            time.sleep(delay)
            continue
        except Exception:
            time.sleep(delay)
            continue
    return False, ""
