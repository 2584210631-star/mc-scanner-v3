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
        """从文件加载排除列表，文件不存在则跳过"""
        before = len(self.networks)
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
            if len(self.networks) == before:
                # 文件存在但一条有效规则都没有：不能静默丢掉私网保护
                # （旧实现只在 FileNotFoundError 分支加载默认段）
                print(f"[!] 排除列表 {filepath} 无有效规则，改用默认私有地址段")
                self._load_defaults()
                return
            self._collapse()
            print(f"[*] 已加载排除列表: {filepath} ({len(self.networks)} 条)")
        except FileNotFoundError:
            print(f"[!] 排除列表文件不存在: {filepath}，使用默认私有地址段")
            self._load_defaults()

    def _collapse(self):
        """合并相邻/重叠网段：is_excluded 是逐个网段线性匹配，合并后大幅减少比较次数"""
        try:
            self.networks = list(ipaddress.collapse_addresses(self.networks))
        except Exception:
            # 混合 IPv4/IPv6 等异常场景保持原样，不影响过滤结果
            pass

    def _load_defaults(self):
        """加载默认私有地址段"""
        defaults = [
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            # 127.0.0.0/8 刻意不在默认列表：与 exclude.conf 一致，支持 scan 127.0.0.1 本机测试
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
        self._collapse()

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
        """过滤目标生成器，排除在列表中的 IP"""
        for ip, port in targets:
            if not self.is_excluded(ip):
                yield (ip, port)
