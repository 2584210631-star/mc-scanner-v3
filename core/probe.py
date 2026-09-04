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
                    if offset >= len(payload):
                        break
                    b = payload[offset]
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
                ver_name = version.get("name", "")
                proto_ver = version.get("protocol", 0)
                fp = fingerprint_server(info, proto_ver)
                return {
                    "state": "up",
                    "version": ver_name,
                    "proto": proto_ver,
                    "motd": _motd_text(info.get("description", "")),
                    "online": players.get("online", 0),
                    "max": players.get("max", 0),
                    "sample": players.get("sample", []),
                    "favicon": info.get("favicon", ""),
                    "ping_ms": ping_ms,
                    "core_type": detect_core_type(ver_name, info),
                    "mods": extract_mods(info),
                    "forge_channels": extract_forge_channels(info),
                    "fingerprint": fp,
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
                    resp_id, resp_payload = _recv_login_response(conn, login_pkts)
                except ConnectionError:
                    last_detail = "连接被关闭（可能白名单/超时/崩溃）"
                    continue

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
                last_detail = f"意外响应 0x{resp_id:02x}"
        except (ConnectionError, OSError, TimeoutError, socket_timeout) as e:
            last_detail = str(e)
    return {"state": STATE_OFFLINE, "detected_proto": None, "detail": last_detail}


def _recv_login_response(conn, login_pkts):
    """读取登录阶段服务端响应；自动处理插件请求（模组服）与压缩设置。

    模组服（Forge/Fabric 等）会在登录阶段发送 LoginPluginRequest，
    必须回一个 declined 的 LoginPluginResponse，否则服务端会一直等待。
    """
    while True:
        resp_id, resp_payload = conn.recv_packet()
        if resp_id == login_pkts.get("cb_plugin_request"):
            try:
                msg_id, _ = read_varint(resp_payload, 0)
                conn.send_packet(login_pkts["sb_plugin_response"],
                                 write_varint(msg_id) + b"\x00")
            except Exception:
                pass
            continue
        if resp_id == login_pkts.get("cb_compress"):
            threshold, _ = read_varint(resp_payload, 0)
            conn.set_compression(threshold)
            continue
        return resp_id, resp_payload


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

def detect_core_type(version_name: str, raw: dict = None) -> str:
    """识别服务器核心类型。
    返回: vanilla / paper / spigot / bukkit / purpur / forge / fabric / neoforge / quilt / catserver / arclight / unknown
    """
    v = (version_name or "").lower()
    if "neoforge" in v:
        return "neoforge"
    if "fabric" in v:
        return "fabric"
    if "quilt" in v:
        return "quilt"
    if "forge" in v or "fml" in v:
        return "forge"
    if "purpur" in v:
        return "purpur"
    if "paper" in v:
        return "paper"
    if "spigot" in v:
        return "spigot"
    if "catserver" in v:
        return "catserver"
    if "arclight" in v:
        return "arclight"
    if "bukkit" in v:
        return "bukkit"
    if raw and isinstance(raw, dict):
        if raw.get("modinfo") or raw.get("forgeData"):
            return "forge"
    return "vanilla" if v else "unknown"

def extract_mods(raw: dict = None) -> list:
    """从 SLP 响应提取模组列表（仅老版本 Forge modinfo 暴露，新版本不暴露）。"""
    if not raw or not isinstance(raw, dict):
        return []
    modinfo = raw.get("modinfo")
    if modinfo and isinstance(modinfo, dict):
        mods = modinfo.get("mods", [])
        if isinstance(mods, list):
            return [{"modid": m.get("modid", ""), "version": m.get("version", "")}
                    for m in mods if isinstance(m, dict)]
    return []

def extract_forge_channels(raw: dict = None) -> list:
    """提取 Forge 插件频道列表（1.13+ Forge SLP forgeData.channels）。"""
    if not raw or not isinstance(raw, dict):
        return []
    forge_data = raw.get("forgeData")
    if forge_data and isinstance(forge_data, dict):
        channels = forge_data.get("channels", [])
        if isinstance(channels, list):
            return [{"res": c.get("res", ""), "version": c.get("version", ""),
                     "required": c.get("required", False)}
                    for c in channels if isinstance(c, dict)]
    return []


def fingerprint_server(raw: dict, proto: int = 0) -> dict:
    """协议指纹识别（参考 matscan passive_fingerprint）。
    通过 SLP JSON 的字段顺序、空 sample、空 favicon 等特征判断服务器软件。
    返回: {field_order, incorrect_order, empty_sample, empty_favicon, likely_software, confidence}
    """
    if not isinstance(raw, dict):
        return {"field_order": "", "incorrect_order": False, "empty_sample": False,
                "empty_favicon": False, "likely_software": "unknown", "confidence": 0}

    # 1.19.4+ (协议762+) Mojang 改了字段顺序为 version, description, players
    if proto >= 762:
        correct_order = ["version", "description", "players"]
    else:
        correct_order = ["description", "players", "version"]

    correct_players_order = ["max", "online"]
    correct_version_order = ["name", "protocol"]

    # 提取顶层字段顺序
    top_keys = [k for k in raw.keys() if k in correct_order]

    players_obj = raw.get("players")
    version_obj = raw.get("version")
    players_keys = []
    version_keys = []
    if isinstance(players_obj, dict):
        players_keys = [k for k in players_obj.keys() if k in correct_players_order]
    if isinstance(version_obj, dict):
        version_keys = [k for k in version_obj.keys() if k in correct_version_order]

    incorrect_order = (top_keys != correct_order or
                       players_keys != correct_players_order or
                       version_keys != correct_version_order)

    # 构建字段顺序描述
    field_order_parts = []
    for key in top_keys:
        if key == "players" and players_keys != correct_players_order:
            field_order_parts.append(f"players({','.join(players_keys)})")
        elif key == "version" and version_keys != correct_version_order:
            field_order_parts.append(f"version({','.join(version_keys)})")
        else:
            field_order_parts.append(key)
    field_order = ",".join(field_order_parts)

    # 空 sample 检测：没人在线时不应有 sample 字段
    empty_sample = False
    online_count = 0
    if isinstance(players_obj, dict):
        online_count = players_obj.get("online", 0)
        sample = players_obj.get("sample")
        if isinstance(sample, list) and len(sample) == 0 and online_count == 0:
            empty_sample = True

    # 空 favicon 检测
    empty_favicon = raw.get("favicon") == ""

    # 基于指纹推断服务器软件
    likely_software = "vanilla"
    confidence = 0
    ver_name = ""
    if isinstance(version_obj, dict):
        ver_name = (version_obj.get("name") or "").lower()

    if incorrect_order:
        confidence += 30
        if "paper" in ver_name:
            likely_software = "paper"
            confidence += 40
        elif "spigot" in ver_name:
            likely_software = "spigot"
            confidence += 40
        elif "purpur" in ver_name:
            likely_software = "purpur"
            confidence += 40
        elif "fabric" in ver_name:
            likely_software = "fabric"
            confidence += 40
        elif "forge" in ver_name or "fml" in ver_name:
            likely_software = "forge"
            confidence += 40
        elif "velocity" in ver_name:
            likely_software = "velocity"
            confidence += 40
        elif "bungee" in ver_name:
            likely_software = "bungeecord"
            confidence += 40
        elif "folia" in ver_name:
            likely_software = "folia"
            confidence += 40
        else:
            # 字段顺序不对但版本名是 vanilla → 很可能是 Paper（Paper 不改版本名）
            likely_software = "paper(推测)"
            confidence += 15
    else:
        # 字段顺序正确
        if "paper" in ver_name:
            likely_software = "paper"
            confidence = 70
        elif "spigot" in ver_name:
            likely_software = "spigot"
            confidence = 70
        elif any(k in ver_name for k in ("vanilla", "1.2", "1.1", "1.7", "1.8", "1.9", "1.10", "1.11", "1.12", "1.13", "1.14", "1.15", "1.16", "1.17", "1.18", "1.19", "1.20", "1.21")):
            likely_software = "vanilla"
            confidence = 60
        else:
            likely_software = "unknown"
            confidence = 10

    if empty_sample:
        confidence += 10  # 空 sample 是非 vanilla 的弱特征
    if empty_favicon:
        confidence += 5

    # Forge/Fabric 数据覆盖
    if raw.get("forgeData") or raw.get("modinfo"):
        likely_software = "forge"
        confidence = 90
    if "neoforge" in ver_name:
        likely_software = "neoforge"
        confidence = 90
    if "fabric" in ver_name:
        likely_software = "fabric"
        confidence = 90

    return {
        "field_order": field_order,
        "correct_order": ",".join(correct_order),
        "incorrect_order": incorrect_order,
        "empty_sample": empty_sample,
        "empty_favicon": empty_favicon,
        "likely_software": likely_software,
        "confidence": min(confidence, 100),
    }


def active_fingerprint(host: str, port: int, proto: int, timeout: float = 4.0) -> dict:
    """主动协议指纹（参考 matscan active fingerprinting）。
    发送 malformed login 请求（用户名长度0+额外数据），根据服务器返回的
    错误消息中的包名识别服务端软件。
    返回: {software, raw_error, confidence}
    """
    import re
    result = {"software": "unknown", "raw_error": "", "confidence": 0}

    try:
        with MCConnection(host, port, timeout) as conn:
            # Handshake: next_state=2 (login)
            conn.handshake(protocol=proto, next_state=PROTO_STATE_LOGIN)

            # Malformed Login Start: 用户名长度=0 + UUID全零 + 额外字节
            login_pkts = get_login_packets()
            pid = login_pkts["sb_start"]
            payload = write_string("")  # 用户名长度0
            if proto >= 764:  # 1.20.2+ 带 UUID
                payload += write_uuid(offline_uuid(""))
            payload += b"\x00"  # 额外数据，触发错误

            conn.send_packet(pid, payload)

            # 读取 disconnect 响应
            try:
                resp_id, resp_payload = _recv_login_response(conn, login_pkts)
            except Exception:
                return result

            if resp_id != login_pkts.get("cb_disconnect", 0x00):
                return result

            msg, _ = read_string(resp_payload, 0)
            result["raw_error"] = msg[:200]

            # matscan 正则: java.io.IOException: Packet N/N (PacketName)
            m = re.search(r"java\.io\.IOException: Packet (?:\d+|login)/\d+ \(([^)]+)\)", msg)
            if m:
                packet_name = m.group(1)
                if packet_name == "PacketLoginInStart":
                    result["software"] = "paper"
                    result["confidence"] = 90
                elif packet_name == "ServerboundHelloPacket":
                    result["software"] = "forge"
                    result["confidence"] = 90
                elif packet_name.startswith("class_"):
                    result["software"] = "fabric"
                    result["confidence"] = 85
                elif 2 <= len(packet_name) <= 3:
                    result["software"] = "vanilla"
                    result["confidence"] = 80
                else:
                    result["software"] = "unknown"
                    result["confidence"] = 20
            elif "Forge" in msg or "FML" in msg or "forge" in msg.lower():
                result["software"] = "forge"
                result["confidence"] = 85
            elif "Paper" in msg:
                result["software"] = "paper"
                result["confidence"] = 80
            elif "Velocity" in msg or "Bungee" in msg or "bungeecord" in msg.lower():
                result["software"] = "proxy"
                result["confidence"] = 75
            elif "netty" in msg.lower() and ("DecoderException" in msg or "CodecException" in msg):
                # Bukkit 系(Paper/Spigot/Purpur)用 netty，错误格式为 DecoderException
                result["software"] = "bukkit_based"
                result["confidence"] = 60
            elif "IOException" in msg and "Packet" in msg:
                # Vanilla 风格错误但包名提取失败
                result["software"] = "vanilla_like"
                result["confidence"] = 40
            elif not msg.strip():
                result["software"] = "empty_response"
                result["confidence"] = 30

    except Exception:
        pass

    return result


def _is_offline_err(e: str) -> bool:
    s = str(e).lower()
    return "timed out" in s or "timeout" in s or "refused" in s or "unreachable" in s
