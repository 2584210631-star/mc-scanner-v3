# -*- coding: utf-8 -*-
"""Bot 错误码枚举，统一错误语义，Web/CLI 直接展示 code + 短消息。"""
from enum import Enum


class BotErrorCode(str, Enum):
    # 协议与表
    NO_PROTOCOL = "no_protocol"           # 无可用协议表（get_play_packets返回None）
    CHAT_ID_MISSING = "chat_id_missing"   # 包表无sb_chat

    # 服务器拒绝
    WHITELIST = "whitelist"               # 白名单拒绝
    ONLINE_MODE_REQUIRED = "online_mode_required"  # 需要正版验证
    BANNED = "banned"                     # 被ban
    KICKED = "kicked"                     # 被踢（附reason）

    # 认证与加密
    ENCRYPT_FAILED = "encrypt_failed"     # 加密握手失败
    MISSING_CRYPTO = "missing_crypto"     # 缺cryptography库
    AUTHME_FAILED = "authme_failed"       # AuthMe登录失败
    TOKEN_EXPIRED = "token_expired"       # 正版token过期

    # 阶段超时
    LOGIN_TIMEOUT = "login_timeout"       # 登录阶段超时
    CONFIG_TIMEOUT = "config_timeout"     # 配置阶段超时（含强进Play）
    PLAY_TIMEOUT = "play_timeout"         # Play阶段超时

    # 连接
    CONNECTION_REFUSED = "connection_refused"  # 连接被拒绝
    CONNECTION_RESET = "connection_reset"      # 连接重置
    NETWORK_ERROR = "network_error"            # 网络错误

    # 模组/兼容
    MOD_REQUIRED = "mod_required"         # 服务器要求模组（如AutoModpack）
    INCOMPATIBLE_VERSION = "incompatible_version"  # 版本不兼容

    # 未知
    UNKNOWN = "unknown"


# 错误码 → 用户可读消息
ERROR_MESSAGES = {
    BotErrorCode.NO_PROTOCOL: "无可用协议表（该版本协议表不完整，建议重新生成）",
    BotErrorCode.CHAT_ID_MISSING: "协议表缺少聊天包ID，无法发送消息",
    BotErrorCode.WHITELIST: "服务器白名单拒绝（账号不在白名单中）",
    BotErrorCode.ONLINE_MODE_REQUIRED: "服务器要求正版验证，请使用正版账号登录",
    BotErrorCode.BANNED: "账号被该服务器封禁",
    BotErrorCode.KICKED: "被服务器踢出",
    BotErrorCode.ENCRYPT_FAILED: "加密握手失败",
    BotErrorCode.MISSING_CRYPTO: "缺少cryptography库，请运行 pip install cryptography",
    BotErrorCode.AUTHME_FAILED: "AuthMe登录失败（密码错误或未注册）",
    BotErrorCode.TOKEN_EXPIRED: "正版token已过期，请重新登录（msa-login）",
    BotErrorCode.LOGIN_TIMEOUT: "登录阶段超时",
    BotErrorCode.CONFIG_TIMEOUT: "配置阶段超时（已强行进入Play，可能不稳定）",
    BotErrorCode.PLAY_TIMEOUT: "Play阶段超时（keep-alive失败）",
    BotErrorCode.CONNECTION_REFUSED: "连接被拒绝（端口未开放或服务器离线）",
    BotErrorCode.CONNECTION_RESET: "连接被重置",
    BotErrorCode.NETWORK_ERROR: "网络错误",
    BotErrorCode.MOD_REQUIRED: "服务器要求安装特定模组",
    BotErrorCode.INCOMPATIBLE_VERSION: "版本不兼容",
    BotErrorCode.UNKNOWN: "未知错误",
}


def get_error_message(code: BotErrorCode) -> str:
    """获取错误码对应的用户可读消息"""
    return ERROR_MESSAGES.get(code, ERROR_MESSAGES[BotErrorCode.UNKNOWN])
