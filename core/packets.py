# -*- coding: utf-8 -*-
"""
多版本 Play 阶段包 ID 表管理。
支持自动生成表（packets_auto.py）优先，回退到手写表。
"""
from .protocol import get_chat_format

# 手写 Play 包 ID 表（按协议版本范围）
# 包含: 聊天/保持连接/登录/传送/断开/插件消息/玩家信息 等常用包
_PLAY_TABLES = [
    # 767: 1.21-1.21.1
    {"min_proto": 767, "max_proto": 767, "sb_chat": 0x06, "sb_chat_command": 0x04,
     "cb_keep_alive": 0x26, "sb_keep_alive": 0x18, "cb_ping": 0x35, "sb_pong": 0x27,
     "cb_login": 0x2B, "cb_teleport": 0x40, "sb_confirm_teleport": 0x00, "cb_disconnect": 0x1D,
     "cb_plugin_message": 0x19, "sb_plugin_message": 0x02, "cb_player_info": 0x38,
     "cb_chat_message": 0x30, "cb_system_chat": 0x62},
    # 766: 1.20.5-1.20.6
    {"min_proto": 766, "max_proto": 766, "sb_chat": 0x06, "sb_chat_command": 0x04,
     "cb_keep_alive": 0x26, "sb_keep_alive": 0x18, "cb_ping": 0x35, "sb_pong": 0x27,
     "cb_login": 0x2B, "cb_teleport": 0x40, "sb_confirm_teleport": 0x00, "cb_disconnect": 0x1D,
     "cb_plugin_message": 0x19, "sb_plugin_message": 0x02, "cb_player_info": 0x38,
     "cb_chat_message": 0x30, "cb_system_chat": 0x62},
    # 765: 1.20.3-1.20.4
    {"min_proto": 765, "max_proto": 765, "sb_chat": 0x05, "sb_chat_command": 0x04,
     "cb_keep_alive": 0x24, "sb_keep_alive": 0x15, "cb_ping": 0x33, "sb_pong": 0x24,
     "cb_login": 0x29, "cb_teleport": 0x38, "sb_confirm_teleport": 0x00, "cb_disconnect": 0x1A,
     "cb_plugin_message": 0x19, "sb_plugin_message": 0x02, "cb_player_info": 0x38,
     "cb_chat_message": 0x35, "cb_system_chat": 0x5F},
    # 764: 1.20.2
    {"min_proto": 764, "max_proto": 764, "sb_chat": 0x05, "sb_chat_command": 0x04,
     "cb_keep_alive": 0x24, "sb_keep_alive": 0x14, "cb_ping": 0x33, "sb_pong": 0x23,
     "cb_login": 0x29, "cb_teleport": 0x38, "sb_confirm_teleport": 0x00, "cb_disconnect": 0x1A,
     "cb_plugin_message": 0x19, "sb_plugin_message": 0x02, "cb_player_info": 0x38,
     "cb_chat_message": 0x35, "cb_system_chat": 0x5F},
    # 768-769: 1.21.2-1.21.4
    {"min_proto": 768, "max_proto": 769, "sb_chat": 0x07, "sb_chat_command": 0x05,
     "cb_keep_alive": 0x27, "sb_keep_alive": 0x1A, "cb_ping": 0x37, "sb_pong": 0x2B,
     "cb_login": 0x2C, "cb_teleport": 0x40, "sb_confirm_teleport": 0x00, "cb_disconnect": 0x1E,
     "cb_plugin_message": 0x1C, "sb_plugin_message": 0x02, "cb_player_info": 0x3E,
     "cb_chat_message": 0x31, "cb_system_chat": 0x67},
    # 770: 1.21.5
    {"min_proto": 770, "max_proto": 770, "sb_chat": 0x07, "sb_chat_command": 0x05,
     "cb_keep_alive": 0x26, "sb_keep_alive": 0x1A, "cb_ping": 0x36, "sb_pong": 0x2B,
     "cb_login": 0x2B, "cb_teleport": 0x40, "sb_confirm_teleport": 0x00, "cb_disconnect": 0x1E,
     "cb_plugin_message": 0x1B, "sb_plugin_message": 0x02, "cb_player_info": 0x3D,
     "cb_chat_message": 0x30, "cb_system_chat": 0x66},
    # 771-772: 1.21.6-1.21.8
    {"min_proto": 771, "max_proto": 772, "sb_chat": 0x08, "sb_chat_command": 0x06,
     "cb_keep_alive": 0x26, "sb_keep_alive": 0x1B, "cb_ping": 0x36, "sb_pong": 0x2C,
     "cb_login": 0x2B, "cb_teleport": 0x40, "sb_confirm_teleport": 0x00, "cb_disconnect": 0x1E,
     "cb_plugin_message": 0x1C, "sb_plugin_message": 0x03, "cb_player_info": 0x3E,
     "cb_chat_message": 0x31, "cb_system_chat": 0x67},
    # 773: 1.21.9
    {"min_proto": 773, "max_proto": 773, "sb_chat": 0x08, "sb_chat_command": 0x06,
     "cb_keep_alive": 0x2B, "sb_keep_alive": 0x1B, "cb_ping": 0x3B, "sb_pong": 0x2C,
     "cb_login": 0x30, "cb_teleport": 0x40, "sb_confirm_teleport": 0x00, "cb_disconnect": 0x1E,
     "cb_plugin_message": 0x1F, "sb_plugin_message": 0x03, "cb_player_info": 0x43,
     "cb_chat_message": 0x36, "cb_system_chat": 0x6C},
    # 774+: 1.21.10+
    {"min_proto": 774, "max_proto": 9999, "sb_chat": 0x08, "sb_chat_command": 0x06,
     "cb_keep_alive": 0x2B, "sb_keep_alive": 0x1B, "cb_ping": 0x3B, "sb_pong": 0x2C,
     "cb_login": 0x30, "cb_teleport": 0x40, "sb_confirm_teleport": 0x00, "cb_disconnect": 0x1E,
     "cb_plugin_message": 0x1F, "sb_plugin_message": 0x03, "cb_player_info": 0x43,
     "cb_chat_message": 0x36, "cb_system_chat": 0x6C},
    # 761-763: 1.19.3-1.20.1
    {"min_proto": 761, "max_proto": 763, "sb_chat": 0x05, "sb_chat_command": 0x04,
     "cb_keep_alive": 0x23, "sb_keep_alive": 0x15, "cb_ping": 0x37, "sb_pong": 0x25,
     "cb_login": 0x25, "cb_teleport": 0x38, "sb_confirm_teleport": 0x00, "cb_disconnect": 0x19,
     "cb_plugin_message": 0x18, "sb_plugin_message": 0x0A, "cb_player_info": 0x34,
     "cb_chat_message": 0x35, "cb_system_chat": 0x5F},
    # 759-760: 1.19
    {"min_proto": 759, "max_proto": 760, "sb_chat": 0x04, "sb_chat_command": None,
     "cb_keep_alive": 0x21, "sb_keep_alive": 0x10, "cb_ping": 0x33, "sb_pong": 0x1F,
     "cb_login": 0x23, "cb_teleport": 0x36, "sb_confirm_teleport": 0x00, "cb_disconnect": 0x17,
     "cb_plugin_message": 0x17, "sb_plugin_message": 0x0A, "cb_player_info": 0x32,
     "cb_chat_message": 0x30, "cb_system_chat": 0x5D},
    # 340-758: 旧版本
    {"min_proto": 340, "max_proto": 758, "sb_chat": 0x03, "sb_chat_command": None,
     "cb_keep_alive": 0x1F, "sb_keep_alive": 0x0E, "cb_ping": 0x2F, "sb_pong": 0x1D,
     "cb_login": 0x23, "cb_teleport": 0x34, "sb_confirm_teleport": 0x00, "cb_disconnect": 0x1A,
     "cb_plugin_message": 0x19, "sb_plugin_message": 0x0A, "cb_player_info": 0x30,
     "cb_chat_message": 0x0F, "cb_system_chat": None},
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
                "cb_plugin_message": cb.get("custom_payload", cb.get("plugin_message")),
                "sb_plugin_message": sb.get("custom_payload", sb.get("plugin_message")),
                "cb_player_info": cb.get("player_info_update", cb.get("player_info")),
                "chat_format": get_chat_format(proto),
                "has_configuration": proto >= 764,
                "login_start_uuid": proto >= 764,
            }
        _auto_tables = auto_play
        print(f"[packets] 已加载自动生成协议表: {len(auto_play)} 个版本")
    except ImportError:
        # packets_auto.py 不存在（可选扩展），使用手写表
        pass
    except Exception as e:
        print(f"[packets] 自动协议表加载失败，回退手写表: {e}")
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
        CONFIG_CB_PLUGIN_MESSAGE, CONFIG_CB_FINISH_CONFIGURATION,
        CONFIG_CB_KEEP_ALIVE, CONFIG_CB_PING,
        CONFIG_CB_DISCONNECT, CONFIG_CB_KNOWN_PACKS,
        CONFIG_SB_CLIENT_INFORMATION, CONFIG_SB_PLUGIN_MESSAGE,
        CONFIG_SB_FINISH_CONFIGURATION,
        CONFIG_SB_KEEP_ALIVE, CONFIG_SB_PONG, CONFIG_SB_KNOWN_PACKS,
    )
    return {
        "cb_plugin_message": CONFIG_CB_PLUGIN_MESSAGE,
        "cb_finish": CONFIG_CB_FINISH_CONFIGURATION,
        "cb_keep_alive": CONFIG_CB_KEEP_ALIVE,
        "cb_ping": CONFIG_CB_PING,
        "cb_disconnect": CONFIG_CB_DISCONNECT,
        "cb_known_packs": CONFIG_CB_KNOWN_PACKS,
        "sb_client_info": CONFIG_SB_CLIENT_INFORMATION,
        "sb_plugin_message": CONFIG_SB_PLUGIN_MESSAGE,
        "sb_finish": CONFIG_SB_FINISH_CONFIGURATION,
        "sb_keep_alive": CONFIG_SB_KEEP_ALIVE,
        "sb_pong": CONFIG_SB_PONG,
        "sb_known_packs": CONFIG_SB_KNOWN_PACKS,
    }


def get_login_packets() -> dict:
    """获取 Login 阶段包 ID（通用）"""
    return {
        "sb_start": 0x00,
        "cb_disconnect": 0x00,
        "cb_encryption": 0x01,
        "cb_success": 0x02,
        "cb_compress": 0x03,
        "cb_plugin_request": 0x04,
        "sb_plugin_response": 0x02,
        "sb_acknowledged": 0x03,
    }


def supported_protos() -> list:
    """返回所有支持的协议版本号"""
    protos = set()
    for table in _PLAY_TABLES:
        protos.add(table["min_proto"])
        if table["max_proto"] < 9999:
            protos.add(table["max_proto"])
    return sorted(protos)
