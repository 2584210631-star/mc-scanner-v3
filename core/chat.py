# -*- coding: utf-8 -*-
"""聊天组件解析（从 bot.py 拆分）。"""
from .nbt import TRANSLATE_MAP

# 递归深度上限：恶意服务器可构造深嵌套组件触发 RecursionError
_MAX_DEPTH = 32


def json_component_to_text(obj, _depth: int = 0) -> str:
    """将 Minecraft JSON 聊天组件转为纯文本（_depth 为内部递归深度，调用方无需传）"""
    if _depth > _MAX_DEPTH:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        parts = []
        if obj.get("text"):
            parts.append(str(obj["text"]))
        if obj.get("translate"):
            trans = str(obj["translate"])
            with_args = obj.get("with", [])
            arg_texts = ([json_component_to_text(a, _depth + 1) for a in with_args]
                         if isinstance(with_args, list) else [])
            # 玩家聊天：with = [sender, message]，只返回消息内容（sender 由 extract_chat_sender 处理）
            if trans == "chat.type.text" and len(arg_texts) >= 2:
                parts.append(arg_texts[1])
            elif trans == "chat.type.emote" and len(arg_texts) >= 2:
                parts.append(f"* {arg_texts[0]} {arg_texts[1]}")
            elif trans == "chat.type.announcement" and len(arg_texts) >= 2:
                parts.append(f"[{arg_texts[0]}] {arg_texts[1]}")
            elif trans == "chat.type.admin" and len(arg_texts) >= 2:
                parts.append(f"[管理员] {arg_texts[0]}: {arg_texts[1]}")
            elif trans == "multiplayer.player.joined" and arg_texts:
                parts.append(f"{arg_texts[0]} 加入了游戏")
            elif trans == "multiplayer.player.left" and arg_texts:
                parts.append(f"{arg_texts[0]} 离开了游戏")
            elif trans.startswith("chat.type.advancement") and len(arg_texts) >= 2:
                friendly = TRANSLATE_MAP.get(trans, trans)
                parts.append(f"{arg_texts[0]} {friendly} [{arg_texts[1]}]")
            elif trans.startswith("death.attack") and arg_texts:
                friendly = TRANSLATE_MAP.get(trans, "死了")
                if len(arg_texts) >= 2:
                    parts.append(f"{arg_texts[0]} {friendly} ({arg_texts[1]})")
                else:
                    parts.append(f"{arg_texts[0]} {friendly}")
            elif trans.startswith("commands.") and arg_texts:
                friendly = TRANSLATE_MAP.get(trans, "")
                if friendly:
                    parts.append(f"{' '.join(arg_texts)} {friendly}")
                else:
                    parts.append(" ".join(arg_texts))
            else:
                # 查翻译表，找不到才保留原始键名
                friendly = TRANSLATE_MAP.get(trans)
                if friendly is not None:
                    if friendly:
                        parts.append(friendly)
                    if arg_texts:
                        parts.append(" " + " ".join(arg_texts))
                else:
                    parts.append(trans)
                    if arg_texts:
                        parts.append(" " + " ".join(arg_texts))
        extra = obj.get("extra")
        if isinstance(extra, list):
            for e in extra:
                parts.append(json_component_to_text(e, _depth + 1))
        return "".join(parts)
    if isinstance(obj, list):
        return "".join(json_component_to_text(e, _depth + 1) for e in obj)
    return str(obj) if obj else ""
