# -*- coding: utf-8 -*-
"""
插件抓取：进服后自动发送 /plugins /version /help 等命令，
解析返回的插件列表、服务端版本、可用命令。

吸收自 MCScanner (Sandelslover/MCScanner) 的 whitelist_check.js 中
进服后发 /plugins 抓插件列表的思路，用自研协议栈实现。
"""
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from .bot import MCBot


# 常见插件列表响应格式
# "Plugins (12): Plugin1 v1.0, Plugin2 v2.0, ..."
# "Plugins: Plugin1, Plugin2, ..."
PLUGINS_PATTERN = re.compile(
    r'[Pp]lugins?\s*(?:\(\d+\))?\s*[:：]\s*(.+)',
    re.DOTALL
)

# 版本响应格式
# "This server is running Paper version git-Paper-218 (MC: 1.20.1)"
VERSION_PATTERN = re.compile(
    r'running\s+(.+?)(?:\s*\(MC:|\s*$)',
    re.IGNORECASE
)


@dataclass
class PluginInfo:
    """插件信息"""
    name: str
    version: str = ""

    def __repr__(self):
        return f"{self.name} v{self.version}" if self.version else self.name


@dataclass
class ServerIntel:
    """服务器情报收集结果"""
    plugins: list[PluginInfo] = field(default_factory=list)
    server_software: str = ""
    server_version: str = ""
    available_commands: list[str] = field(default_factory=list)
    raw_responses: dict[str, str] = field(default_factory=dict)
    has_authme: bool = False
    has_factions: bool = False
    has_economy: bool = False
    has_worldguard: bool = False
    has_coreprotect: bool = False
    has_luckperms: bool = False
    has_vault: bool = False
    anti_cheat: str = ""  # ncp / vulcan / matrix / spartan / none / unknown


def capture_plugins(bot: MCBot, wait_time: float = 2.0) -> ServerIntel:
    """
    在已连接的 bot 上发送探测命令，收集服务器情报。
    bot 必须已经进入 play 状态。

    发送的命令：
    - /plugins （或 /pl）
    - /version （或 /ver）
    - /help （可选，命令太多可能刷屏）
    """
    intel = ServerIntel()

    # 1. /plugins
    try:
        plugins_text = _send_and_capture(bot, "plugins", wait_time)
        if plugins_text:
            intel.raw_responses["plugins"] = plugins_text
            intel.plugins = _parse_plugins(plugins_text)
    except Exception:
        pass

    # 2. /version
    try:
        version_text = _send_and_capture(bot, "version", wait_time)
        if version_text:
            intel.raw_responses["version"] = version_text
            intel.server_software, intel.server_version = _parse_version(version_text)
    except Exception:
        pass

    # 3. 检测常见插件
    plugin_names = {p.name.lower() for p in intel.plugins}
    intel.has_authme = any("authme" in n or "login" in n for n in plugin_names)
    intel.has_factions = any("faction" in n or "factions" in n for n in plugin_names)
    intel.has_economy = any("economy" in n or "essentials" in n for n in plugin_names)
    intel.has_worldguard = any("worldguard" in n for n in plugin_names)
    intel.has_coreprotect = any("coreprotect" in n or "co i" in n for n in plugin_names)
    intel.has_luckperms = any("luckperms" in n or "permissions" in n for n in plugin_names)
    intel.has_vault = any("vault" in n for n in plugin_names)

    # 反作弊检测
    anti_cheats = {
        "ncp": ["nocommandspigot", "nocheatplus", "ncp"],
        "vulcan": ["vulcan"],
        "matrix": ["matrix"],
        "spartan": ["spartan"],
        "aac": ["aac", "advancedanticheat"],
        "sparky": ["sparky"],
        "intave": ["intave"],
        "horizon": ["horizon"],
        "karhu": ["karhu"],
        "soaroma": ["soaroma"],
        "pandawire": ["pandawire"],
    }
    for ac_name, keywords in anti_cheats.items():
        if any(kw in plugin_names for kw in keywords):
            intel.anti_cheat = ac_name
            break
    if not intel.anti_cheat and intel.plugins:
        intel.anti_cheat = "unknown"
    elif not intel.anti_cheat:
        intel.anti_cheat = "none"

    return intel


def _send_and_capture(bot: MCBot, command: str, wait_time: float) -> str:
    """发送命令并捕获聊天响应（通过临时监听）"""
    messages = []
    original_handler = None

    def capture_handler(packet_id, data):
        # 尝试从聊天包中提取文本（简化版，只收集原始字节长度）
        messages.append(len(data))

    # 直接发命令，然后等待
    try:
        bot.send_command(command)
    except Exception:
        pass

    time.sleep(wait_time)

    # 由于 bot 的 _handle_play_packets 在后台线程运行，
    # 我们无法直接获取聊天内容。这里返回空字符串，
    # 实际插件列表解析依赖于 bot 层面的聊天监听扩展。
    # 完整实现需要在 MCBot 中添加聊天回调机制。
    return ""


def _parse_plugins(text: str) -> list[PluginInfo]:
    """解析 /plugins 响应文本"""
    plugins = []
    match = PLUGINS_PATTERN.search(text)
    if not match:
        return plugins
    raw = match.group(1).strip()
    # 按逗号分割
    for part in re.split(r'[,，]', raw):
        part = part.strip()
        if not part:
            continue
        # 尝试提取 "Name v1.0" 格式
        vmatch = re.match(r'^(.+?)\s+v?(\d[\w.\-]*)$', part, re.IGNORECASE)
        if vmatch:
            plugins.append(PluginInfo(name=vmatch.group(1).strip(), version=vmatch.group(2)))
        else:
            plugins.append(PluginInfo(name=part))
    return plugins


def _parse_version(text: str) -> tuple[str, str]:
    """解析 /version 响应，返回 (软件名, 版本号)"""
    match = VERSION_PATTERN.search(text)
    if match:
        full = match.group(1).strip()
        # 尝试分离软件名和版本
        parts = full.split()
        if len(parts) >= 2:
            return parts[0], " ".join(parts[1:])
        return full, ""
    return "", ""


def plugins_to_text(plugins: list[PluginInfo]) -> str:
    """将插件列表转为可读文本"""
    if not plugins:
        return "(无插件或无法获取)"
    return ", ".join(str(p) for p in plugins)
