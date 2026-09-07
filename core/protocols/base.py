"""协议处理器基类 — 每个版本继承并实现自己的格式"""
from __future__ import annotations
from typing import Optional, Tuple


class ProtocolHandler:
    """版本协议处理器基类。子类只负责自己版本的包格式。"""

    protocol_version: int = 0
    version_name: str = "unknown"

    def __init__(self, bot):
        self.bot = bot

    # ---- 登录阶段 ----
    def login_start_payload(self, username: str, uuid: Optional[str] = None) -> bytes:
        """构造 Login Start 包 payload"""
        raise NotImplementedError

    # ---- 配置阶段 ----
    def do_configuration(self) -> bool:
        """处理 Configuration 阶段，返回是否成功"""
        return True

    # ---- 聊天发送 ----
    def send_chat_payload(self, message: str) -> bytes:
        """构造聊天消息包 payload"""
        raise NotImplementedError

    def send_command_payload(self, command: str) -> bytes:
        """构造命令包 payload（不含前导 /）"""
        raise NotImplementedError

    # ---- 聊天接收 ----
    def extract_chat_text(self, data: bytes, is_system: bool) -> str:
        """从聊天包提取纯文本"""
        return ""

    def extract_chat_sender(self, data: bytes) -> str:
        """从聊天包提取发送者名字"""
        return "未知玩家"

    # ---- Play 阶段包处理 ----
    def handle_play_packet(self, packet_id: int, data: bytes) -> bool:
        """处理一个 play 阶段包。返回 True 表示已处理，False 表示未识别。"""
        return False
