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
    try:
        info = json.loads(banner)
        return _extract_info(info)
    except json.JSONDecodeError:
        pass

    # 尝试从 banner 中提取 JSON 部分
    json_match = re.search(r'\{.*\}', banner, re.DOTALL)
    if json_match:
        try:
            info = json.loads(json_match.group())
            return _extract_info(info)
        except json.JSONDecodeError:
            pass

    return None


def _extract_info(info: dict) -> dict:
    """从 SLP JSON 中提取标准化信息"""
    version = info.get("version", {})
    players = info.get("players", {})
    desc = info.get("description", "")

    motd = ""
    if isinstance(desc, str):
        motd = desc
    elif isinstance(desc, dict):
        motd = desc.get("text", str(desc))

    return {
        "version": version.get("name", ""),
        "proto": version.get("protocol", 0),
        "motd": motd[:500],
        "online": players.get("online", 0),
        "max": players.get("max", 0),
        "sample": players.get("sample", []),
        "favicon": info.get("favicon", ""),
        "is_modded": _looks_modded(version.get("name", "")),
    }


def _looks_modded(version: str) -> int:
    """判断服务器是否为模组服"""
    v = version.lower()
    keywords = ("forge", "fabric", "mod", "paper", "spigot",
                "bukkit", "purpur", "fml", "arclight", "catserver")
    return 1 if any(kw in v for kw in keywords) else 0


def extract_records(ndjson_path: str) -> list:
    """
    从 masscan NDJSON 结果文件中提取 (ip, port, banner) 记录。
    """
    from .masscan import parse_masscan_json
    return parse_masscan_json(ndjson_path)
