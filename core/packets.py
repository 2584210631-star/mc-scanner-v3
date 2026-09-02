# -*- coding: utf-8 -*-
"""
多版本 Play 阶段包 ID 表管理。
支持自动生成表（packets_auto.py）优先，回退到手写表。
"""
from .protocol import get_chat_format

# 手写 Play 包 ID 表（按协议版本范围）
# 每个表包含: sb_chat, sb_chat_command, cb_keep_alive, sb_keep_alive,
#            cb_ping, sb_pong, cb_login, cb_teleport, sb_confirm_teleport, cb_disconnect
_PLAY_TABLES = [
    {
        "min_proto": 766, "max_proto": 9999,
        "sb_chat": 0x08, "sb_chat_command": 0x06,
        "cb_keep_alive": 0x2B, "sb_keep_alive": 0x1B,
        "cb_ping": 0x3E, "sb_pong": 0x2C,
        "cb_login": 0x30, "cb_teleport": 0x3E,
        "sb_confirm_teleport": 0x00, "cb_disconnect": 0x20,
    },
    {
        "min_proto": 764, "max_proto": 765,
        "sb_chat": 0x08, "sb_chat_command": 0x06,
        "cb_keep_alive": 0x2A, "sb_keep_alive": 0x1A,
        "cb_ping": 0x3D, "sb_pong": 0x2B,
        "cb_login": 0x2B, "cb_teleport": 0x3D,
        "sb_confirm_teleport": 0x00, "cb_disconnect": 0x1E,
    },
    {
        "min_proto": 761, "max_proto": 763,
        "sb_chat": 0x05, "sb_chat_command": 0x04,
        "cb_keep_alive": 0x23, "sb_keep_alive": 0x15,
        "cb_ping": 0x37, "sb_pong": 0x25,
        "cb_login": 0x25, "cb_teleport": 0x38,
        "sb_confirm_teleport": 0x00, "cb_disconnect": 0x19,
    },
    {
        "min_proto": 759, "max_proto": 760,
        "sb_chat": 0x04, "sb_chat_command": None,
        "cb_keep_alive": 0x21, "sb_keep_alive": 0x10,
        "cb_ping": 0x33, "sb_pong": 0x1F,
        "cb_login": 0x23, "cb_teleport": 0x36,
        "sb_confirm_teleport": 0x00, "cb_disconnect": 0x17,
    },
    {
        "min_proto": 340, "max_proto": 758,
        "sb_chat": 0x03, "sb_chat_command": None,
        "cb_keep_alive": 0x1F, "sb_keep_alive": 0x0E,
        "cb_ping": 0x2F, "sb_pong": 0x1D,
        "cb_login": 0x23, "cb_teleport": 0x34,
        "sb_confirm_teleport": 0x00, "cb_disconnect": 0x1A,
    },
]

_auto_tables = None
_auto_loaded = False


def _load_auto_tables():
    """尝试加载 packets_auto.py 生成的协议表"""
    global _auto_tables, _auto_loaded
    if _auto_loaded:
        return _auto_tables
    _auto_loaded = True
    try:
        from packets_auto import PACKET_TABLES_AUTO
        from .protocol import PROTOCOL_TO_VERSION
        ver_to_proto = {v: k for k, v in PROTOCOL_TO_VERSION.items()}
        auto_play = {}
        for ver_name, stages in PACKET_TABLES_AUTO.items():
            proto = ver_to_proto.get(ver_name)
            if proto is None:
                continue
            play = stages.get("play", {})
            sb = play.get("toServer", {})
            cb = play.get("toClient", {})
            auto_play[proto] = {
                "min_proto": proto, "max_proto": proto,
                "sb_chat": sb.get("chat", sb.get("chat_message")),
                "sb_chat_command": sb.get("chat_command", sb.get("chat_command_signed")),
                "cb_keep_alive": cb.get("keep_alive"),
                "sb_keep_alive": sb.get("keep_alive"),
                "cb_ping": cb.get("ping", cb.get("ping_pong")),
                "sb_pong": sb.get("pong", sb.get("ping_pong")),
                "cb_login": cb.get("login", cb.get("join_game")),
                "chat_format": get_chat_format(proto),
                "has_configuration": proto >= 764,
                "login_start_uuid": proto >= 764,
            }
        _auto_tables = auto_play
        print(f"[packets] 已加载自动生成协议表: {len(auto_play)} 个版本")
    except ImportError:
        pass
    except Exception as e:
        print(f"[packets] 自动协议表加载失败: {e}")
    return _auto_tables


def get_play_packets(proto: int) -> dict | None:
    """获取指定协议版本的 Play 包 ID 表"""
    auto = _load_auto_tables()
    if auto and proto in auto:
        return auto[proto]
    for table in _PLAY_TABLES:
        if table["min_proto"] <= proto <= table["max_proto"]:
            result = dict(table)
            result["chat_format"] = get_chat_format(proto)
            result["has_configuration"] = proto >= 764
            result["login_start_uuid"] = proto >= 764
            return result
    return None


def get_config_packets(proto: int) -> dict | None:
    """获取 Configuration 阶段包 ID（1.20.2+ 通用）"""
    if proto < 764:
        return None
    from .protocol import (
        CONFIG_CB_FINISH_CONFIGURATION, CONFIG_CB_KEEP_ALIVE, CONFIG_CB_PING,
        CONFIG_CB_DISCONNECT, CONFIG_CB_KNOWN_PACKS,
        CONFIG_SB_CLIENT_INFORMATION, CONFIG_SB_FINISH_CONFIGURATION,
        CONFIG_SB_KEEP_ALIVE, CONFIG_SB_PONG, CONFIG_SB_KNOWN_PACKS,
    )
    return {
        "cb_finish": CONFIG_CB_FINISH_CONFIGURATION,
        "cb_keep_alive": CONFIG_CB_KEEP_ALIVE,
        "cb_ping": CONFIG_CB_PING,
        "cb_disconnect": CONFIG_CB_DISCONNECT,
        "cb_known_packs": CONFIG_CB_KNOWN_PACKS,
        "sb_client_info": CONFIG_SB_CLIENT_INFORMATION,
        "sb_finish": CONFIG_SB_FINISH_CONFIGURATION,
        "sb_keep_alive": CONFIG_SB_KEEP_ALIVE,
        "sb_pong": CONFIG_SB_PONG,
        "sb_known_packs": CONFIG_SB_KNOWN_PACKS,
    }


def get_login_packets() -> dict:
    """获取 Login 阶段包 ID（全版本通用）"""
    from .protocol import (
        LOGIN_CB_DISCONNECT, LOGIN_CB_ENCRYPTION_REQUEST, LOGIN_CB_LOGIN_SUCCESS,
        LOGIN_CB_SET_COMPRESSION, LOGIN_SB_LOGIN_START, LOGIN_SB_LOGIN_ACKNOWLEDGED,
    )
    return {
        "cb_disconnect": LOGIN_CB_DISCONNECT,
        "cb_encryption": LOGIN_CB_ENCRYPTION_REQUEST,
        "cb_success": LOGIN_CB_LOGIN_SUCCESS,
        "cb_compress": LOGIN_CB_SET_COMPRESSION,
        "sb_start": LOGIN_SB_LOGIN_START,
        "sb_acknowledged": LOGIN_SB_LOGIN_ACKNOWLEDGED,
    }


def supported_protos() -> list:
    """返回所有支持的协议版本列表"""
    auto = _load_auto_tables()
    protos = set()
    if auto:
        protos.update(auto.keys())
    for table in _PLAY_TABLES:
        protos.add(table["min_proto"])
        if table["max_proto"] < 9999:
            protos.add(table["max_proto"])
    return sorted(protos)
