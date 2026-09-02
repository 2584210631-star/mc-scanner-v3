"""
随机 IP + 随机端口 暴力扫描模块
生成随机公网 IP 和端口，批量扫描寻找 Minecraft 服务器
"""
import random
import socket
import ipaddress
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterator, Tuple, List, Optional

# 排除的私有/保留地址段
EXCLUDED_NETWORKS = [
    ipaddress.ip_network('0.0.0.0/8'),
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('100.64.0.0/10'),
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.0.0.0/24'),
    ipaddress.ip_network('192.0.2.0/24'),
    ipaddress.ip_network('192.88.99.0/24'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('198.18.0.0/15'),
    ipaddress.ip_network('198.51.100.0/24'),
    ipaddress.ip_network('203.0.113.0/24'),
    ipaddress.ip_network('224.0.0.0/4'),
    ipaddress.ip_network('240.0.0.0/4'),
]

# Minecraft 常见端口范围
DEFAULT_PORT_RANGES = [
    (25565, 25575),   # 默认 MC 端口范围
    (19132, 19133),   # Bedrock
    (25500, 25600),   # 扩展范围
    (1, 65535),       # 全端口（暴力模式）
]


def is_public_ip(ip_str: str) -> bool:
    """检查是否为公网 IP"""
    try:
        ip = ipaddress.ip_address(ip_str)
        for net in EXCLUDED_NETWORKS:
            if ip in net:
                return False
        return True
    except ValueError:
        return False


def random_public_ip() -> str:
    """生成一个随机公网 IP"""
    while True:
        ip = f"{random.randint(1, 223)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
        if is_public_ip(ip):
            return ip


def random_port(port_ranges: Optional[List[Tuple[int, int]]] = None) -> int:
    """从端口范围中随机选择一个端口"""
    if port_ranges is None:
        port_ranges = [(25565, 25575)]
    # 随机选一个范围，再在范围内随机选端口
    start, end = random.choice(port_ranges)
    return random.randint(start, end)


def generate_random_targets(count: int, port_ranges: Optional[List[Tuple[int, int]]] = None) -> Iterator[Tuple[str, int]]:
    """生成随机 (ip, port) 目标"""
    for _ in range(count):
        yield random_public_ip(), random_port(port_ranges)


def check_port(ip: str, port: int, timeout: float = 2.0) -> bool:
    """检查端口是否开放"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except:
        return False


def random_scan(
    target_count: int = 1000,
    max_workers: int = 200,
    timeout: float = 2.0,
    port_ranges: Optional[List[Tuple[int, int]]] = None,
    progress_callback=None,
    stop_event: Optional[threading.Event] = None,
) -> List[Tuple[str, int]]:
    """
    随机扫描：生成随机 IP+端口，批量扫描
    返回开放的 (ip, port) 列表
    """
    targets = list(generate_random_targets(target_count, port_ranges))
    open_ports = []
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_port, ip, port, timeout): (ip, port) for ip, port in targets}
        for future in as_completed(futures):
            if stop_event and stop_event.is_set():
                break
            ip, port = futures[future]
            done += 1
            try:
                if future.result():
                    open_ports.append((ip, port))
            except:
                pass
            if progress_callback:
                progress_callback(done, target_count, len(open_ports))

    return open_ports


def parse_port_ranges(spec: str) -> List[Tuple[int, int]]:
    """解析端口范围字符串，如 '25565-25575,19132-19133'"""
    ranges = []
    for part in spec.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-', 1)
            ranges.append((int(start), int(end)))
        elif part:
            p = int(part)
            ranges.append((p, p))
    return ranges if ranges else [(25565, 25575)]
