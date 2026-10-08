# -*- coding: utf-8 -*-
"""
目标解析：支持 IP / CIDR / 主机名 / IP:端口 / CIDR:端口 / 文件。
惰性生成器，大网段不 OOM。
"""
import ipaddress
import socket
from typing import Iterator, Optional

MAX_TARGETS = 2_000_000
# @文件最大嵌套深度：自引用/环形引用会让旧实现直接 RecursionError
MAX_FILE_DEPTH = 8


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
                # 只保留 1..65535：非法端口流到 socket/masscan 只会产生无意义报错
                for p in range(max(start, 1), min(end, 65535) + 1):
                    ports.add(p)
            except ValueError:
                continue
        else:
            try:
                p = int(part)
            except ValueError:
                continue
            if 1 <= p <= 65535:
                ports.add(p)
    return sorted(ports)


def _split_addr_port(target: str):
    """拆出 (地址, 端口)，无端口时端口为 None"""
    if target.count(':') == 1:
        parts = target.rsplit(':', 1)
        if parts[1].isdigit():
            return parts[0], int(parts[1])
    return target, None


def _host_estimate(network) -> int:
    """网段可用主机数：/31 是 RFC3021 点对点网段（两个地址都可用），/32 只有一个。"""
    n = network.num_addresses
    if n <= 2:
        return n
    return n - 2


def _iter_hosts(network):
    """惰性产出可用主机（大网段不物化）"""
    if network.num_addresses <= 2:
        return iter(network)
    return network.hosts()


def _parse_file(filepath: str, default_ports, depth: int, state: dict) -> Iterator:
    """流式读取目标文件，支持嵌套 @文件并限制递归深度"""
    if depth >= MAX_FILE_DEPTH:
        print(f"[!] @文件嵌套超过 {MAX_FILE_DEPTH} 层，忽略: {filepath}")
        return
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # 逐行递归：既流式（不再整文件读入内存）又能传递深度与共享计数
                yield from parse_targets([line], default_ports, depth + 1, state)
    except FileNotFoundError:
        print(f"[!] 目标文件不存在: {filepath}")
    except OSError as e:
        print(f"[!] 读取目标文件失败 {filepath}: {e}")


def parse_targets(targets: list, default_ports: Optional[list] = None,
                  _depth: int = 0, _state: dict = None) -> Iterator:
    """
    解析目标列表（惰性生成器）。
    支持：单个IP、IP:端口、CIDR网段、CIDR:端口、主机名、主机名:端口、@文件路径

    _depth/_state 为内部参数：@文件递归共享同一个计数器，
    避免旧实现"每次递归重置 count"绕过 MAX_TARGETS 上限。
    """
    if default_ports is None:
        default_ports = [25565]
    if _state is None:
        _state = {"count": 0}
    for target in targets:
        target = target.strip()
        if not target or target.startswith('#'):
            continue
        if target.startswith('@'):
            yield from _parse_file(target[1:], default_ports, _depth, _state)
            continue

        addr_part, port = _split_addr_port(target)

        try:
            network = ipaddress.ip_network(addr_part, strict=False)
            est = _host_estimate(network) * (1 if port else len(default_ports))
            if _state["count"] + est > MAX_TARGETS:
                print(f"[!] 目标 {target} 约 {est} 个，超过上限 {MAX_TARGETS}，已跳过")
                continue
            for ip in _iter_hosts(network):
                if port is not None:
                    _state["count"] += 1
                    yield (str(ip), port)
                else:
                    for p in default_ports:
                        _state["count"] += 1
                        yield (str(ip), p)
        except ValueError:
            try:
                resolved = socket.gethostbyname(addr_part)
                if port is not None:
                    _state["count"] += 1
                    yield (resolved, port)
                else:
                    for p in default_ports:
                        _state["count"] += 1
                        yield (resolved, p)
            except socket.gaierror:
                print(f"[!] 无法解析: {addr_part}")


def _count_targets(targets, default_ports, depth: int, state: dict):
    """count_targets 的递归实现（与 parse_targets 相同的估算/跳过策略）"""
    for target in targets:
        target = target.strip()
        if not target or target.startswith('#'):
            continue
        if target.startswith('@'):
            filepath = target[1:]
            if depth >= MAX_FILE_DEPTH:
                continue
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        _count_targets([line], default_ports, depth + 1, state)
            except FileNotFoundError:
                pass
            except OSError:
                pass
            continue
        addr_part, port = _split_addr_port(target)
        try:
            network = ipaddress.ip_network(addr_part, strict=False)
            est = _host_estimate(network) * (1 if port else len(default_ports))
            if state["count"] + est > MAX_TARGETS:
                continue
            state["count"] += est
        except ValueError:
            try:
                socket.gethostbyname(addr_part)
                state["count"] += 1 if port else len(default_ports)
            except socket.gaierror:
                pass


def count_targets(targets: list, default_ports: Optional[list] = None) -> int:
    """快速估算目标总数（不物化），支持@文件递归统计。

    与 parse_targets 共用同一套估算与超限跳过策略，
    避免旧实现"count 返回 min(count, MAX)=200 万、parse 实际 0 条"的不一致。
    """
    if default_ports is None:
        default_ports = [25565]
    state = {"count": 0}
    _count_targets(targets, default_ports, 0, state)
    return state["count"]


def deduplicate_targets(targets: list) -> list:
    """去重目标列表。

    注意：需要 set + list 全量驻留，仅适合中小规模；百万级目标请用分块扫描
    （scan_ports / scan_ports_async 不做去重，重复目标按业务侧自行分片处理）。
    """
    seen = set()
    result = []
    for ip, port in targets:
        key = (ip, port)
        if key not in seen:
            seen.add(key)
            result.append((ip, port))
    return result
