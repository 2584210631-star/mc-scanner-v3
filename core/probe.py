# -*- coding: utf-8 -*-
"""
探测核心：SLP 元数据采集 + 认证模式（在线/破解/白名单/拒绝）检测。
融合 V1 的协议回退和 V2 的 JSON 截断容错（Hypixel 等节点兼容）。
"""
import json
import socket
import time
from .buffer import (write_varint, write_string, read_string, write_uuid,
                     read_varint, offline_uuid)
from .conn import MCConnection, PROTO_STATE_STATUS, PROTO_STATE_LOGIN
from .packets import get_play_packets, get_login_packets, supported_protos
from .protocol import COMMON_PROTOCOLS

socket_timeout = socket.timeout

# 认证状态常量
STATE_ONLINE = "online"        # 正版验证
STATE_CRACKED = "cracked"      # 离线/破解
STATE_WHITELIST = "whitelist"  # 白名单
STATE_REJECTED = "rejected"    # 被拒绝
STATE_OFFLINE = "offline"      # 不可达
STATE_ERROR = "error"          # 其它错误


def slp_probe(host: str, port: int, timeout: float = 5.0,
               protocol_version: int = -1, retries: int = 2) -> dict | None:
    """
    Server List Ping：获取服务器信息（版本/玩家/MOTD/延迟）。
    protocol_version=-1 时使用特殊值请求服务器返回真实版本。
    吸收 V2 的 JSON 截断容错：某些服务器声明的 JSON 长度比实际少几个字节。
    """
    last_error = None
    for attempt in range(retries + 1):
        try:
            with MCConnection(host, port, timeout) as conn:
                conn.handshake(protocol=protocol_version, next_state=PROTO_STATE_STATUS)
                conn.send_packet(0x00, b"")  # Status Request
                pid, payload = conn.recv_packet()
                if pid != 0x00:
                    last_error = f"意外响应包 0x{pid:02x}"
                    continue

                # 解析 JSON 长度（VarInt）
                if len(payload) < 3:
                    last_error = "SLP payload 过短"
                    continue
                length = 0
                offset = 0
                for i in range(5):
                    if offset + i >= len(payload):
                        break
                    b = payload[offset + i]
                    length |= (b & 0x7F) << (7 * i)
                    offset += 1
                    if not (b & 0x80):
                        break

                jstr = payload[offset:offset + length].decode("utf-8", errors="replace")
                try:
                    info = json.loads(jstr)
                except json.JSONDecodeError:
                    # V2 容错：JSON 长度声明不完整，拼上多余字节再解析
                    extra = payload[offset + length:]
                    if extra:
                        jstr2 = (payload[offset:offset + length] + extra).decode("utf-8", errors="replace")
                        try:
                            info = json.loads(jstr2)
                        except json.JSONDecodeError:
                            last_error = "SLP JSON 解析失败"
                            continue
                    else:
                        last_error = "SLP JSON 解析失败"
                        continue

                # Ping 测延迟
                ping_start = time.time()
                conn.send_packet(0x01, b"\x00\x00\x00\x00\x00\x00\x00\x00")
                try:
                    conn.recv_packet()
                except Exception:
                    pass
                ping_ms = int((time.time() - ping_start) * 1000)

                version = info.get("version", {})
                players = info.get("players", {})
                return {
                    "state": "up",
                    "version": version.get("name", ""),
                    "proto": version.get("protocol", 0),
                    "motd": _motd_text(info.get("description", "")),
                    "online": players.get("online", 0),
                    "max": players.get("max", 0),
                    "sample": players.get("sample", []),
                    "favicon": info.get("favicon", ""),
                    "ping_ms": ping_ms,
                    "_raw": info,
                }
        except (ConnectionError, OSError, TimeoutError, socket_timeout, ValueError, KeyError, IndexError) as e:
            last_error = str(e)
            continue
    return {"state": STATE_OFFLINE if _is_offline_err(last_error) else STATE_ERROR,
            "error": last_error}


def probe_with_fallback(host: str, port: int, timeout: float = 5.0) -> dict | None:
    """SLP 探测带协议回退：先用 -1 探测，失败则尝试常见协议号"""
    result = slp_probe(host, port, timeout, protocol_version=-1)
    if result and result.get("state") == "up":
        return result
    for proto in COMMON_PROTOCOLS:
        result = slp_probe(host, port, timeout, protocol_version=proto)
        if result and result.get("state") == "up":
            result["_used_protocol"] = proto
            return result
    return result


def auth_probe(host: str, port: int, reported_proto: int, username: str = "ScannerTest",
               timeout: float = 4.0, try_versions: list | None = None) -> dict:
    """
    认证模式检测：登录握手试探。
    返回: state / detected_proto / detail
    """
    protos = try_versions or [reported_proto if reported_proto and reported_proto > 0 else None]
    if protos[0] is None:
        protos = list(reversed(supported_protos()))

    seen = set()
    last_detail = ""
    login_pkts = get_login_packets()

    for proto in protos:
        if proto in seen:
            continue
        seen.add(proto)
        try:
            with MCConnection(host, port, timeout) as conn:
                conn.handshake(protocol=proto, next_state=PROTO_STATE_LOGIN)
                play_pkts = get_play_packets(proto)
                pid = login_pkts["sb_start"]
                payload = write_string(username)
                if proto >= 764:  # 1.20.2+ 带 UUID
                    payload += write_uuid(offline_uuid(username))
                conn.send_packet(pid, payload)

                try:
                    resp_id, resp_payload = conn.recv_packet()
                except ConnectionError:
                    last_detail = "连接被关闭"
                    return {"state": STATE_WHITELIST, "detected_proto": proto,
                            "detail": "login disconnect"}

                if resp_id == login_pkts["cb_success"]:
                    return {"state": STATE_CRACKED, "detected_proto": proto,
                            "detail": "login success (离线/破解服)"}
                if resp_id == login_pkts["cb_encryption"]:
                    return {"state": STATE_ONLINE, "detected_proto": proto,
                            "detail": "encryption requested (正版验证)"}
                if resp_id == login_pkts["cb_disconnect"]:
                    msg, _ = read_string(resp_payload, 0)
                    low = msg.lower()
                    if "whitelist" in low:
                        return {"state": STATE_WHITELIST, "detected_proto": proto,
                                "detail": f"whitelist: {msg[:80]}"}
                    return {"state": STATE_REJECTED, "detected_proto": proto,
                            "detail": f"rejected: {msg[:80]}"}
                if resp_id == login_pkts["cb_compress"]:
                    threshold, _ = read_varint(resp_payload, 0)
                    conn.set_compression(threshold)
                    resp_id, resp_payload = conn.recv_packet()
                    if resp_id == login_pkts["cb_success"]:
                        return {"state": STATE_CRACKED, "detected_proto": proto,
                                "detail": "login success (压缩)"}
                    if resp_id == login_pkts["cb_encryption"]:
                        return {"state": STATE_ONLINE, "detected_proto": proto,
                                "detail": "encryption requested (压缩)"}
                    if resp_id == login_pkts["cb_disconnect"]:
                        msg, _ = read_string(resp_payload, 0)
                        low = msg.lower()
                        return {"state": STATE_WHITELIST if "whitelist" in low else STATE_REJECTED,
                                "detected_proto": proto, "detail": msg[:80]}
                last_detail = f"意外响应 0x{resp_id:02x}"
        except (ConnectionError, OSError, TimeoutError, socket_timeout) as e:
            last_detail = str(e)
    return {"state": STATE_OFFLINE, "detected_proto": None, "detail": last_detail}


def _motd_text(desc) -> str:
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        if "text" in desc:
            return desc["text"]
        extra = desc.get("extra")
        if isinstance(extra, list):
            return "".join(_motd_text(e) for e in extra)
    return str(desc)


def _is_offline_err(e: str) -> bool:
    s = str(e).lower()
    return "timed out" in s or "timeout" in s or "refused" in s or "unreachable" in s
