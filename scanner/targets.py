# -*- coding: utf-8 -*-
"""
目标解析：支持 IP / CIDR / 主机名 / IP:端口 / CIDR:端口 / 文件。
惰性生成器，大网段不 OOM。
"""
import ipaddress
import socket
from typing import Iterator, Optional

MAX_TARGETS = 2_000_000


def parse_port_spec(spec: str) -> list:
    """解析端口规格：'25565' / '25565,25566' / '25565-25575' / 混合"""
    ports = set()
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                start, end = int(start), int(end)
                if start > end:
                    start, end = end, start
                for p in range(start, min(end, 65535) + 1):
                    ports.add(p)
            except ValueError:
                continue
        else:
            try:
                ports.add(int(part))
            except ValueError:
                continue
    return sorted(ports)


def parse_targets(targets: list, default_ports: Optional[list] = None) -> Iterator:
    """
    解析目标列表（惰性生成器）。
    支持：单个IP、IP:端口、CIDR网段、CIDR:端口、主机名、主机名:端口、@文件路径
    """
    if default_ports is None:
        default_ports = [25565]
    count = 0
    for target in targets:
        target = target.strip()
        if not target or target.startswith('#'):
            continue
        if target.startswith('@'):
            filepath = target[1:]
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    file_targets = [line.strip() for line in f if line.strip() and not line.startswith('#')]
                yield from parse_targets(file_targets, default_ports)
            except FileNotFoundError:
                print(f"[!] 目标文件不存在: {filepath}")
            continue

        addr_part = target
        port = None
        if target.count(':') == 1:
            parts = target.rsplit(':', 1)
            if parts[1].isdigit():
                addr_part = parts[0]
                port = int(parts[1])

        try:
            network = ipaddress.ip_network(addr_part, strict=False)
            num_hosts = network.num_addresses - 2 if network.num_addresses > 2 else 1
            est = num_hosts * (1 if port else len(default_ports))
            if count + est > MAX_TARGETS:
                print(f"[!] 目标 {target} 约 {est} 个，超过上限 {MAX_TARGETS}，已跳过")
                continue
            hosts = network.hosts() if network.num_addresses > 2 else [network.network_address]
            for ip in hosts:
                if port is not None:
                    count += 1
                    yield (str(ip), port)
                else:
                    for p in default_ports:
                        count += 1
                        yield (str(ip), p)
        except ValueError:
            try:
                resolved = socket.gethostbyname(addr_part)
                if port is not None:
                    count += 1
                    yield (resolved, port)
                else:
                    for p in default_ports:
                        count += 1
                        yield (resolved, p)
            except socket.gaierror:
                print(f"[!] 无法解析: {addr_part}")


def count_targets(targets: list, default_ports: Optional[list] = None) -> int:
    """快速估算目标总数（不物化），支持@文件递归统计"""
    if default_ports is None:
        default_ports = [25565]
    count = 0
    for target in targets:
        target = target.strip()
        if not target or target.startswith('#'):
            continue
        if target.startswith('@'):
            filepath = target[1:]
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    file_targets = [line.strip() for line in f if line.strip() and not line.startswith('#')]
                count += count_targets(file_targets, default_ports)
            except FileNotFoundError:
                pass
            continue
        addr_part = target
        port = None
        if target.count(':') == 1:
            parts = target.rsplit(':', 1)
            if parts[1].isdigit():
                addr_part = parts[0]
                port = int(parts[1])
        try:
            network = ipaddress.ip_network(addr_part, strict=False)
            num_hosts = network.num_addresses - 2 if network.num_addresses > 2 else 1
            count += num_hosts * (1 if port else len(default_ports))
        except ValueError:
            try:
                socket.gethostbyname(addr_part)
                count += 1 if port else len(default_ports)
            except socket.gaierror:
                pass
    return min(count, MAX_TARGETS)


def deduplicate_targets(targets: list) -> list:
    """去重目标列表"""
    seen = set()
    result = []
    for ip, port in targets:
        key = (ip, port)
        if key not in seen:
            seen.add(key)
            result.append((ip, port))
    return result
