# -*- coding: utf-8 -*-
"""
异步 SLP 探测 + 认证检测。
用 asyncio 实现 MC 协议握手，比同步 socket 快 3-10 倍。
复用 core/buffer.py 的 VarInt 编解码和 core/protocol.py 的协议号。
可选 pysimdjson 加速 JSON 解析。
"""
import asyncio
import json
import time
import atexit
import concurrent.futures

from core.buffer import write_varint, read_varint
from core.protocol import COMMON_PROTOCOLS
from core.probe import detect_core_type, extract_mods, extract_forge_channels, _motd_text

# 全局认证检测线程池（避免每次调用创建/销毁）
_AUTH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=100, thread_name_prefix="auth-probe")


def _shutdown_executor():
    """程序退出时关闭全局线程池"""
    try:
        _AUTH_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass


atexit.register(_shutdown_executor)

try:
    import simdjson
    _HAS_SIMDJSON = True
    _parser = simdjson.Parser()
except ImportError:
    _HAS_SIMDJSON = False


def _parse_json(data: bytes):
    """解析 JSON，优先用 simdjson，回退标准库。"""
    if _HAS_SIMDJSON:
        try:
            return json.loads(_parser.parse(data).as_dict())
        except Exception:
            pass
    try:
        return json.loads(data)
    except Exception:
        return None


async def _recv_exact(reader: asyncio.StreamReader, n: int) -> bytes:
    """精确读取 n 字节。"""
    data = b""
    while len(data) < n:
        chunk = await reader.read(n - len(data))
        if not chunk:
            break
        data += chunk
    return data


async def _recv_packet(reader: asyncio.StreamReader):
    """读取一个 MC 数据包（长度前缀）。"""
    # 读取包长度（VarInt）
    length_bytes = b""
    while True:
        b = await _recv_exact(reader, 1)
        if not b:
            return None, None
        length_bytes += b
        if not (b[0] & 0x80):
            break
        if len(length_bytes) > 5:
            return None, None
    try:
        length, _ = read_varint(length_bytes, 0)
    except Exception:
        return None, None
    if length <= 0 or length > 4 * 1024 * 1024:
        return None, None
    payload = await _recv_exact(reader, length)
    if len(payload) < length:
        return None, None
    # 解析包 ID
    try:
        packet_id, offset = read_varint(payload, 0)
    except Exception:
        return None, None
    return packet_id, payload[offset:]


def _build_handshake(host: str, port: int, proto: int) -> bytes:
    """构建 Handshake 包。"""
    data = write_varint(0x00)  # Packet ID
    data += write_varint(proto)  # Protocol Version
    # Server Address (string)
    host_bytes = host.encode("utf-8")
    data += write_varint(len(host_bytes)) + host_bytes
    data += port.to_bytes(2, "big")  # Server Port
    data += write_varint(1)  # Next State: Status (1)
    return write_varint(len(data)) + data


def _build_status_request() -> bytes:
    """构建 Status Request 包。"""
    data = write_varint(0x00)
    return write_varint(len(data)) + data


def _build_ping(payload: int) -> bytes:
    """构建 Ping 包。"""
    data = write_varint(0x01) + payload.to_bytes(8, "big", signed=True)
    return write_varint(len(data)) + data


async def async_slp_probe(ip: str, port: int, timeout: float = 4.0) -> dict:
    """
    异步 SLP 探测。

    Returns:
        dict with state/version/proto/motd/online/max/sample/favicon/ping_ms/
             core_type/mods/forge_channels
    """
    last_error = ""
    for proto in COMMON_PROTOCOLS:
        try:
            start = time.time()
            connect_fut = asyncio.open_connection(ip, port)
            reader, writer = await asyncio.wait_for(connect_fut, timeout=timeout)

            # 发送 Handshake + Status Request
            writer.write(_build_handshake(ip, port, proto))
            writer.write(_build_status_request())
            await writer.drain()

            # 接收 Status Response
            packet_id, payload = await asyncio.wait_for(
                _recv_packet(reader), timeout=timeout)

            if packet_id != 0x00 or not payload:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                last_error = f"bad packet id={packet_id}"
                continue

            # 解析 JSON 长度前缀
            try:
                json_len, offset = read_varint(payload, 0)
                json_data = payload[offset:offset + json_len]
            except Exception:
                json_data = payload

            info = _parse_json(json_data)
            if not info:
                # Hypixel 等服务器可能截断 JSON，尝试修复
                try:
                    raw = json_data.decode("utf-8", errors="replace")
                    # 找到最后一个完整的 }
                    idx = raw.rfind("}")
                    if idx > 0:
                        info = json.loads(raw[:idx + 1])
                except Exception:
                    pass

            if not info:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                last_error = "json parse failed"
                continue

            # Ping 测量
            ping_ms = None
            try:
                ping_payload = int(time.time() * 1000) & 0xFFFFFFFFFFFFFFFF
                writer.write(_build_ping(ping_payload))
                await writer.drain()
                pong_id, _ = await asyncio.wait_for(
                    _recv_packet(reader), timeout=2.0)
                if pong_id == 0x01:
                    ping_ms = int((time.time() - start) * 1000)
            except Exception:
                ping_ms = int((time.time() - start) * 1000)

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            version = info.get("version", {})
            players = info.get("players", {})
            ver_name = version.get("name", "")

            return {
                "state": "up",
                "version": ver_name,
                "proto": version.get("protocol", 0),
                "motd": _motd_text(info.get("description", "")),
                "online": players.get("online", 0),
                "max": players.get("max", 0),
                "sample": players.get("sample", []),
                "favicon": info.get("favicon", ""),
                "ping_ms": ping_ms,
                "core_type": detect_core_type(ver_name, info),
                "mods": extract_mods(info),
                "forge_channels": extract_forge_channels(info),
                "_raw": info,
            }

        except asyncio.TimeoutError:
            last_error = "timeout"
            continue
        except (ConnectionRefusedError, OSError) as e:
            last_error = str(e)[:80]
            continue
        except Exception as e:
            last_error = str(e)[:80]
            continue

    return {"state": "offline", "error": last_error}


async def async_auth_probe(ip: str, port: int, proto: int = 0,
                           timeout: float = 4.0) -> dict:
    """
    异步认证模式检测（简化版，实际登录握手）。
    返回 state: online/cracked/whitelist/rejected/offline/error
    """
    from core.probe import auth_probe

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _AUTH_EXECUTOR, lambda: auth_probe(ip, port, reported_proto=proto, timeout=timeout))
    # 统一返回格式：auth_mode 字段兼容旧代码
    if isinstance(result, dict) and 'state' in result and 'auth_mode' not in result:
        result['auth_mode'] = result['state']
    return result


def has_simdjson() -> bool:
    return _HAS_SIMDJSON
