# -*- coding: utf-8 -*-
"""
Discord Webhook 通知（v3.2.1 新增，融合 matscan 特性）。
支持：玩家上下线通知、新服务器发现通知、离线服发现通知。
纯 urllib 实现，不依赖第三方库（与原版 vendored 依赖风格一致）。
"""
import json
import time
import urllib.request
import urllib.error


class DiscordNotifier:
    """Discord Webhook 通知器。"""

    def __init__(self, webhook_url: str = "", username: str = "MC Scanner",
                 avatar_url: str = "", enabled: bool = None):
        self.webhook_url = webhook_url
        self.username = username
        self.avatar_url = avatar_url
        self.enabled = enabled if enabled is not None else bool(webhook_url)
        self._last_notify = {}  # 防重复通知

    def send(self, content: str = None, embed: dict = None) -> bool:
        """发送 Discord 消息。"""
        if not self.enabled or not self.webhook_url:
            return False
        payload = {
            "username": self.username,
            "content": content or "",
        }
        if self.avatar_url:
            payload["avatar_url"] = self.avatar_url
        if embed:
            payload["embeds"] = [embed]

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 204)
        except (urllib.error.URLError, urllib.error.HTTPError, Exception):
            return False

    def notify_new_server(self, server: dict):
        """新服务器发现通知。"""
        key = f"new_{server.get('ip')}:{server.get('port')}"
        if self._should_skip(key, cooldown=86400):
            return
        auth = server.get("auth", "unknown")
        auth_emoji = {"cracked": "🔓", "online": "🔒", "whitelist": "📋"}.get(auth, "❓")
        core_type = server.get("core_type", server.get("server_type", "未知"))
        embed = {
            "title": "🆕 发现新服务器",
            "color": 0x3498DB,
            "fields": [
                {"name": "地址", "value": f"{server.get('ip')}:{server.get('port')}", "inline": True},
                {"name": "版本", "value": server.get("version", "未知") or "未知", "inline": True},
                {"name": "认证", "value": f"{auth_emoji} {auth}", "inline": True},
                {"name": "服务端", "value": str(core_type), "inline": True},
                {"name": "在线", "value": f"{server.get('players_online', 0)}/{server.get('players_max', 0)}", "inline": True},
                {"name": "MOTD", "value": str(server.get("motd", ""))[:100] or "无", "inline": False},
            ],
            "timestamp": _iso_now(),
        }
        if self.send(embed=embed):
            self._last_notify[key] = time.time()

    def notify_cracked_server(self, server: dict):
        """发现离线/破解服通知。"""
        key = f"cracked_{server.get('ip')}:{server.get('port')}"
        if self._should_skip(key, cooldown=86400):
            return
        embed = {
            "title": "🔓 发现离线模式服务器",
            "color": 0xE74C3C,
            "description": f"**{server.get('ip')}:{server.get('port')}** 处于离线模式，可能存在安全风险",
            "fields": [
                {"name": "版本", "value": server.get("version", "未知") or "未知", "inline": True},
                {"name": "MOTD", "value": str(server.get("motd", ""))[:100] or "无", "inline": False},
            ],
            "timestamp": _iso_now(),
        }
        if self.send(embed=embed):
            self._last_notify[key] = time.time()

    def notify_player_join(self, server: dict, player_name: str):
        """玩家上线通知。"""
        key = f"join_{server.get('ip')}:{server.get('port')}_{player_name}"
        if self._should_skip(key, cooldown=300):
            return
        embed = {
            "title": "🎮 玩家上线",
            "color": 0x00FF00,
            "fields": [
                {"name": "玩家", "value": player_name, "inline": True},
                {"name": "服务器", "value": f"{server.get('ip')}:{server.get('port')}", "inline": True},
                {"name": "在线", "value": f"{server.get('players_online', 0)}/{server.get('players_max', 0)}", "inline": True},
            ],
            "timestamp": _iso_now(),
        }
        if self.send(embed=embed):
            self._last_notify[key] = time.time()

    def notify_player_leave(self, server: dict, player_name: str):
        """玩家下线通知。"""
        key = f"leave_{server.get('ip')}:{server.get('port')}_{player_name}"
        if self._should_skip(key, cooldown=300):
            return
        embed = {
            "title": "👋 玩家下线",
            "color": 0xFF0000,
            "fields": [
                {"name": "玩家", "value": player_name, "inline": True},
                {"name": "服务器", "value": f"{server.get('ip')}:{server.get('port')}", "inline": True},
            ],
            "timestamp": _iso_now(),
        }
        if self.send(embed=embed):
            self._last_notify[key] = time.time()

    def _should_skip(self, key: str, cooldown: int = 300) -> bool:
        """检查是否在冷却期内（防重复通知）。"""
        last = self._last_notify.get(key, 0)
        return (time.time() - last) < cooldown


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
