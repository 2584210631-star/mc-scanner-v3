# -*- coding: utf-8 -*-
"""
排除列表：过滤私有地址、云厂商段等。
每行一个 CIDR，支持 # 注释。
"""
import ipaddress
from typing import Optional


class Excluder:
    """IP 排除过滤器"""

    def __init__(self, exclude_file: Optional[str] = None):
        self.networks = []
        if exclude_file:
            self.load(exclude_file)

    def load(self, filepath: str):
        """从文件加载排除列表"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    try:
                        self.networks.append(ipaddress.ip_network(line, strict=False))
                    except ValueError:
                        continue
            print(f"[*] 已加载排除列表: {filepath} ({len(self.networks)} 条)")
        except FileNotFoundError:
            print(f"[!] 排除列表文件不存在: {filepath}，使用默认私有地址段")
            self._load_defaults()

    def _load_defaults(self):
        """加载默认私有地址段"""
        defaults = [
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "127.0.0.0/8",
            "0.0.0.0/8",
            "169.254.0.0/16",
            "224.0.0.0/4",
            "240.0.0.0/4",
        ]
        for cidr in defaults:
            try:
                self.networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                pass

    def is_excluded(self, ip: str) -> bool:
        """检查 IP 是否在排除列表中"""
        try:
            addr = ipaddress.ip_address(ip)
            for network in self.networks:
                if addr in network:
                    return True
        except ValueError:
            pass
        return False

    def filter_targets(self, targets):
        """过滤目标生成器，排除不在列表中的 IP"""
        for ip, port in targets:
            if not self.is_excluded(ip):
                yield (ip, port)
