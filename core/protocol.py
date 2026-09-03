# -*- coding: utf-8 -*-
"""
协议常量与版本映射表。
支持 Minecraft 1.12.2 ~ 最新版本（协议 340+）。
"""

# 最新协议版本（Minecraft 1.21.11）
LATEST_PROTOCOL = 774

# 连接状态
STATE_HANDSHAKE = 0
STATE_STATUS = 1
STATE_LOGIN = 2
STATE_CONFIGURATION = 3
STATE_PLAY = 4

# --- Login Clientbound ---
LOGIN_CB_DISCONNECT = 0x00
LOGIN_CB_ENCRYPTION_REQUEST = 0x01
LOGIN_CB_LOGIN_SUCCESS = 0x02
LOGIN_CB_SET_COMPRESSION = 0x03
LOGIN_CB_LOGIN_PLUGIN_REQUEST = 0x04

# --- Login Serverbound ---
LOGIN_SB_LOGIN_START = 0x00
LOGIN_SB_LOGIN_PLUGIN_RESPONSE = 0x02
LOGIN_SB_LOGIN_ACKNOWLEDGED = 0x03

# --- Configuration Clientbound (1.20.2+, 协议 764+) ---
CONFIG_CB_PLUGIN_MESSAGE = 0x01
CONFIG_CB_DISCONNECT = 0x02
CONFIG_CB_FINISH_CONFIGURATION = 0x03
CONFIG_CB_KEEP_ALIVE = 0x04
CONFIG_CB_PING = 0x05
CONFIG_CB_KNOWN_PACKS = 0x0E
CONFIG_CB_ADD_RESOURCE_PACK = 0x09

# --- Configuration Serverbound ---
CONFIG_SB_CLIENT_INFORMATION = 0x00
CONFIG_SB_PLUGIN_MESSAGE = 0x02
CONFIG_SB_FINISH_CONFIGURATION = 0x03
CONFIG_SB_KEEP_ALIVE = 0x04
CONFIG_SB_PONG = 0x05
CONFIG_SB_RESOURCE_PACK_RESPONSE = 0x06
CONFIG_SB_KNOWN_PACKS = 0x07

# 协议号 -> 版本名 映射
PROTOCOL_TO_VERSION = {
    340: "1.12.2",
    393: "1.13",
    401: "1.13.1",
    404: "1.13.2",
    477: "1.14",
    480: "1.14.1",
    485: "1.14.2",
    490: "1.14.3",
    498: "1.14.4",
    573: "1.15",
    575: "1.15.1",
    578: "1.15.2",
    735: "1.16",
    736: "1.16.1",
    751: "1.16.2",
    753: "1.16.3",
    754: "1.16.4/5",
    755: "1.17",
    756: "1.17.1",
    757: "1.18/1.18.1",
    758: "1.18.2",
    759: "1.19",
    760: "1.19.1/2",
    761: "1.19.3",
    762: "1.19.4",
    763: "1.20/1.20.1",
    764: "1.20.2",
    765: "1.20.3/4",
    766: "1.20.5/6",
    767: "1.21/1.21.1",
    768: "1.21.2",
    769: "1.21.3",
    770: "1.21.4/5",
    771: "1.21.6",
    772: "1.21.7",
    773: "1.21.8/9/10",
    774: "1.21.11",
    775: "1.21.12+",
}

# 常见协议版本（用于协议回退）
COMMON_PROTOCOLS = [774, 770, 767, 766, 765, 764, 763, 762, 761, 760, 759, 758, 757, 756, 755, 754, 340]


def get_version_name(proto: int) -> str:
    """协议号转版本名"""
    if proto in PROTOCOL_TO_VERSION:
        return PROTOCOL_TO_VERSION[proto]
    if proto > 775:
        return f"1.21.12+ (协议{proto})"
    return f"未知 (协议{proto})"


def get_chat_format(proto: int) -> str:
    """根据协议版本返回聊天消息格式类型
    返回: 'new' (766+), 'old_signed_761' (761-765), 'old_signed_760' (760),
          'old_signed_759' (759), 'simple' (<759)
    """
    if proto >= 766:
        return "new"
    if proto >= 761:
        return "old_signed_761"
    if proto >= 760:
        return "old_signed_760"
    if proto >= 759:
        return "old_signed_759"
    return "simple"
