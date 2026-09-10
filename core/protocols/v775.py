"""Minecraft 26.1（协议 775）协议处理器，继承 774
26.1 聊天包格式变化：hasSignature+messageCount → signature(option)+offset
但无签名时编码结果与 774 相同（都是 0x00），故直接复用"""
from __future__ import annotations
from .v774 import Handler as V774Handler


class Handler(V774Handler):
    protocol_version = 775
    version_name = "26.1"
