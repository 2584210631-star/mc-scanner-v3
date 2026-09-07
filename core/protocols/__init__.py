"""协议处理器工厂 — 根据协议版本号返回对应版本的处理器"""
from __future__ import annotations
from typing import Optional


def get_protocol_handler(bot) -> Optional[object]:
    """根据 bot.protocol_version 返回对应版本的协议处理器"""
    proto = bot.protocol_version
    if proto is None:
        return None

    if proto >= 774:
        from .v774 import Handler
    elif proto >= 766:
        from .v766 import Handler
    elif proto >= 761:
        from .v761 import Handler
    elif proto >= 760:
        from .v760 import Handler
    elif proto >= 759:
        from .v759 import Handler
    else:
        from .v758 import Handler

    return Handler(bot)
