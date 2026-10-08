# -*- coding: utf-8 -*-
"""
masscan banner 解析：从 SLP banner 中提取服务器信息。
masscan 的 --banners 功能可以直接抓取 SLP 响应。
"""
import json
import re
from typing import Optional


def parse_banner(banner: str) -> Optional[dict]:
    """
    解析 masscan 抓取的 SLP banner，返回服务器信息字典。
    banner 可能是原始 JSON 字符串，也可能包含额外前缀。
    """
    if not banner:
        return None

    # 尝试直接解析 JSON
    # banner 完全由目标服务器控制：除 JSONDecodeError 外还可能出现 TypeError 等，
    # 任何异常都不允许穿透（旧实现只 catch JSONDecodeError，畸形 banner 会中断整批导入）
    try:
        info = json.loads(banner)
        return _extract_info(info)
    except Exception:
        pass

    # 尝试从 banner 中提取 JSON 部分
    try:
        json_match = re.search(r'\{.*\}', banner, re.DOTALL)
        if json_match:
            info = json.loads(json_match.group())
            return _extract_info(info)
    except Exception:
        pass

    return None


def _extract_info(info) -> dict:
    """从 SLP JSON 中提取标准化信息。

    version/players 等嵌套字段由远端控制、类型不可信（可能是 str/int），
    一律用 isinstance 兜底，避免 AttributeError 穿透后中断调用方。
    """
    if not isinstance(info, dict):
        info = {}
    version = info.get("version", {})
    if isinstance(version, dict):
        ver_name = version.get("name", "")
        proto = version.get("protocol", 0)
    else:
        # 少数服务端把 version 直接写成字符串/数字，当作版本名保留，不丢信息
        ver_name, proto = version, 0
    players = info.get("players", {})
    if not isinstance(players, dict):
        players = {}
    sample = players.get("sample", [])
    if not isinstance(sample, list):
        sample = []
    desc = info.get("description", "")

    motd = ""
    if isinstance(desc, str):
        motd = desc
    elif isinstance(desc, dict):
        motd = desc.get("text", str(desc))

    if ver_name is None:
        ver_name = ""
    if not isinstance(ver_name, str):
        ver_name = str(ver_name)

    return {
        "version": ver_name,
        "proto": proto,
        "motd": motd[:500],
        "online": players.get("online", 0),
        "max": players.get("max", 0),
        "sample": sample,
        "favicon": info.get("favicon", ""),
        "is_modded": _looks_modded(ver_name),
    }


def _looks_modded(version: str) -> int:
    """判断服务器是否为模组服（仅 Forge/Fabric/NeoForge/Quilt 等，不含插件服）"""
    v = version.lower()
    keywords = ("forge", "fabric", "neoforge", "quilt", "fml", "modloader",
                "arclight", "catserver", "mohist", "magma")
    return 1 if any(kw in v for kw in keywords) else 0


def extract_records(ndjson_path: str) -> list:
    """
    从 masscan NDJSON 结果文件中提取 (ip, port, banner) 记录。
    """
    from .masscan import parse_masscan_json
    return parse_masscan_json(ndjson_path)
