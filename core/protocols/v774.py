"""1.21.11+（协议 774+）协议处理器，继承 766 仅覆盖差异"""
from __future__ import annotations
import struct, time
from .v766 import Handler as V766Handler
from ..buffer import write_string


class Handler(V766Handler):
    protocol_version = 774
    version_name = "1.21.11+"

    # send_chat_payload 继承 v766，1.21.11+ 聊天包格式未变
