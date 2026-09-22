# -*- coding: utf-8 -*-
"""聊天组件解析（从 bot.py 拆分）。"""
from .nbt import TRANSLATE_MAP


def json_component_to_text(obj) -> str:
    """将 Minecraft JSON 聊天组件转为纯文本"""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        parts = []
        if obj.get("text"):
            parts.append(str(obj["text"]))
        if obj.get("translate"):
            trans = str(obj["translate"])
            with_args = obj.get("with", [])
            arg_texts = [json_component_to_text(a) for a in with_args] if isinstance(with_args, list) else []
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
                parts.append(json_component_to_text(e))
        return "".join(parts)
    if isinstance(obj, list):
        return "".join(json_component_to_text(e) for e in obj)
    return str(obj) if obj else ""
